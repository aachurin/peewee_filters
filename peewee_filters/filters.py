import inspect
import itertools
import peewee
import typing
import datetime
import uuid
from peewee import ForeignKeyField, BackrefAccessor

Query = peewee.ModelSelect

OPERATORS = {
    "eq": "__eq__",
    "lt": "__lt__",
    "gt": "__gt__",
    "le": "__le__",
    "ge": "__ge__",
    "ne": "__ne__",
    "=": "__eq__",
    "<": "__lt__",
    "<=": "__le__",
    ">": "__gt__",
    ">=": "__ge__",
    "!=": "__ne__",
    "%": "__mod__",
    "**": "__pow__",
    "like": "__mod__",
    "ilike": "__pow__",
    "is_null": "is_null",
    "in": "in_",
    "not_in": "not_in",
    "contains": "contains",
    "startswith": "startswith",
    "endswith": "endswith",
    "^": "startswith",
    "$": "endswith",
    "regexp": "regexp",
    "iregexp": "iregexp"
}


class Parameter(typing.NamedTuple):
    annotation: typing.Type
    description: str = ""
    default: typing.Any = None


class Filter:

    field_and_joins: typing.Tuple[peewee.Field, typing.List[peewee.Field]] = None

    def __init__(
            self,
            field_name: str = None,
            description: str = "",
            operator: str = "eq",
            default: typing.Any = None
    ):
        self.description = description
        self.field_name = field_name
        self.default = default
        try:
            self.operator = OPERATORS[operator]
        except KeyError:
            raise TypeError(f"No such operator `{operator}`.")
        self.escape_value = self.operator in ("contains", "startswith", "endswith")

    def get_model_field_and_joins(
            self,
            model: peewee.Model,
            field_name: str
    ) -> typing.Tuple[peewee.Field, typing.List[peewee.Field]]:
        joins = []
        if "." in field_name:
            *fields, field_name = field_name.split(".")
            for field in fields:
                try:
                    field = getattr(model, field)
                    joins.append(field)
                    model = field.rel_model
                except AttributeError:
                    raise TypeError(
                        f"Field `{field}` does not exist on model {model.__name__} or is not relationship."
                    )
        try:
            field = getattr(model, field_name)
        except AttributeError:
            raise TypeError(
                f"Field `{field_name}` does not exist on model {model.__name__}."
            )
        if isinstance(field, BackrefAccessor):
            joins.append(field)
            field = field.rel_model._meta.primary_key
        return field, joins

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        field, joins = self.get_model_field_and_joins(model, self.field_name)
        key = field.rel_field if isinstance(field, ForeignKeyField) else type(field)
        mapping = PEEWEE_FIELD_MAPPING
        for cls in key.__mro__:
            if cls in mapping:
                suitable_class = mapping[cls]
                break
        else:
            raise TypeError(
                f"Could not choose suitable filter for field `{key.__name__}`."
            )
        return self.clone(cls=suitable_class, field_and_joins=(field, joins))

    def ensure_join(
            self,
            query: Query,
            joins: typing.List[peewee.Field]
    ) -> Query:
        distinct = False
        query = query.clone()
        for field in joins:
            if isinstance(field, ForeignKeyField):
                query = query.ensure_join(field.model, field.rel_model, field)
            else:
                assert isinstance(field, BackrefAccessor)
                query = query.ensure_join(field.model, field.rel_model, field.field)
                distinct = True
        if distinct:
            query = query.distinct()
        return query

    def get_annotation(self, filterset):
        raise TypeError(f"Not a concrete filter.")

    def clone(self, cls=None, **kwargs) -> "Filter":
        cls = cls or self.__class__
        obj = cls.__new__(cls)
        obj.__dict__ = self.__dict__.copy()
        obj.__dict__.update(kwargs)
        return obj

    def apply(
            self,
            filterset,
            query: Query,
            value: typing.Any,
            context: typing.Any = None
    ) -> Query:
        raise TypeError(f"Can apply only concrete filters.")


class MethodFilter(Filter):
    def __init__(self, method: typing.Union[typing.Callable, str], **kwargs):
        super().__init__(**kwargs)
        self.method = method

    def get_annotation(self, filterset):
        method = self.method if callable(self.method) else getattr(filterset, self.method)
        try:
            parameter = inspect.signature(method).parameters["value"]
        except KeyError:
            raise TypeError(f"Method `{method.__name__}` is not suitable for filtering.")
        default = None if parameter.default is inspect.Signature.empty else parameter.default
        return Parameter(
            parameter.annotation,
            default=default,
            description=self.description
        )

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        return self

    def apply(
            self,
            filterset,
            query: Query,
            value: typing.Any,
            context: typing.Any = None
    ) -> Query:
        if callable(self.method):
            method = self.method
        else:
            method = getattr(filterset, self.method)
        return method(
            query=query,
            field_name=self.field_name,
            value=value,
            context=context
        )


class ConcreteFilter(Filter):
    python_type = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.check_operator()

    def check_operator(self):
        string_only = (
            "__mod__", "__pow__", "contains", "startswith", "endswith", "regexp", "iregexp"
        )
        if self.operator in string_only:
            operator = self.operator
            if operator == "__mod__":
                operator = "like"
            elif operator == "__pow__":
                operator = "ilike"
            raise TypeError(
                f"Operator `{operator}` is not suitable for {self.__class__.__name__}."
            )

    def get_annotation(self, filterset):
        if self.operator == "is_null":
            ann = bool
        elif self.operator in ("in_", "not_in"):
            ann = typing.List[self.python_type]
        else:
            ann = self.python_type
        return Parameter(ann, description=self.description, default=self.default)

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        field, joins = self.get_model_field_and_joins(model, self.field_name)
        key = field.rel_field if isinstance(field, ForeignKeyField) else type(field)
        candidates = PEEWEE_FIELD_REVERSE_MAPPING[self.__class__]
        # noinspection PyTypeHints
        if not issubclass(key, candidates):
            raise TypeError(
                f"Filter `{self.__class__.__name__}` is not suitable for field `{key.__name__}`"
            )
        return self.clone(field_and_joins=(field, joins))

    def apply(
            self,
            filterset,
            query: Query,
            value: typing.Any,
            context: typing.Any = None
    ) -> Query:
        if self.field_and_joins is not None:
            field, joins = self.field_and_joins
        else:
            field, joins = self.get_model_field_and_joins(query.model, self.field_name)
        if joins:
            query = self.ensure_join(query, joins)
        if self.escape_value:
            value = value.replace("\\", "\\\\").replace("_", "\\_").replace("%", "\\%")
        return query.where(getattr(field, self.operator)(value))


class CharFilter(ConcreteFilter):
    python_type = str

    def check_operator(self):
        pass


class NumberFilter(ConcreteFilter):
    python_type = float


class DateTimeFilter(ConcreteFilter):
    python_type = datetime.datetime


class TimeFilter(ConcreteFilter):
    python_type = datetime.time


class DateFilter(ConcreteFilter):
    python_type = datetime.date


class BooleanFilter(ConcreteFilter):
    python_type = bool


class UUIDFilter(ConcreteFilter):
    python_type = uuid.UUID


PEEWEE_FIELD_MAPPING = {
    peewee.AutoField: NumberFilter,
    peewee.BigAutoField: NumberFilter,
    peewee.IntegerField: NumberFilter,
    peewee.BigIntegerField: NumberFilter,
    peewee.SmallIntegerField: NumberFilter,
    peewee.FloatField: NumberFilter,
    peewee.DoubleField: NumberFilter,
    peewee.DecimalField: NumberFilter,
    peewee.CharField: CharFilter,
    peewee.FixedCharField: CharFilter,
    peewee.TextField: CharFilter,
    peewee.DateTimeField: DateTimeFilter,
    peewee.DateField: DateFilter,
    peewee.TimeField: TimeFilter,
    peewee.BooleanField: BooleanFilter,
    peewee.BinaryUUIDField: UUIDFilter
}


PEEWEE_FIELD_REVERSE_MAPPING = {
    k: tuple(x[0] for x in v)
    for k, v in itertools.groupby(
        sorted(list(PEEWEE_FIELD_MAPPING.items()), key=lambda x: id(x[1])),
        key=lambda x: x[1]
    )
}


class OffsetFilter(Filter):
    def get_annotation(self, filterset):
        return Parameter(int, description=self.description, default=self.default)

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        return self

    def apply(
            self,
            filterset,
            query: Query,
            value: int,
            context: typing.Any = None
    ) -> Query:
        return query.offset(max(0, value))


class LimitFilter(Filter):
    def __init__(self, default=100, maximum=None, **kwargs):
        super().__init__(**kwargs)
        self.default = default
        self.maximum = maximum

    def get_annotation(self, filterset):
        return Parameter(int, description=self.description, default=self.default)

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        return self

    def apply(
            self,
            filterset,
            query: Query,
            value: int,
            context: typing.Any = None
    ) -> Query:
        if self.maximum is not None:
            value = min(value, self.maximum)
        return query.limit(max(0, value))


class OrderingFilter(Filter):
    field_and_joins: typing.Dict[str, typing.Tuple[peewee.Field, typing.List[peewee.Field]]] = None

    def __init__(
            self,
            fields: typing.Union[typing.List[str], typing.Dict[str, str]],
            default: typing.List[str] = None,
            **kwargs
    ):
        super().__init__(**kwargs)
        if isinstance(fields, list):
            self.fields = {k: k for k in fields}
        else:
            self.fields = fields
        self.default = default

    def get_annotation(self, filterset):
        return Parameter(typing.List[str], description=self.description, default=self.default)

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        field_and_joins = {}
        for k, v in self.fields.items():
            field_and_joins[k] = self.get_model_field_and_joins(model, v)
        return self.clone(field_and_joins=field_and_joins)

    def apply(
            self,
            filterset,
            query: Query,
            value: typing.List[str],
            context: typing.Any = None
    ) -> Query:
        order_by = []
        for field in value:
            if field.startswith("-"):
                desc = True
                field = field[1:]
            else:
                desc = False
            if self.field_and_joins is not None:
                if field not in self.field_and_joins:
                    continue
                field, joins = self.field_and_joins[field]
            else:
                if field not in self.fields:
                    continue
                field, joins = self.get_model_field_and_joins(query.model, self.fields[field])
            if joins:
                query = self.ensure_join(query, joins)
            order_by.append(field.desc() if desc else field)
        return query.order_by_extend(*order_by)


class SearchingFilter(Filter):
    field_and_joins: typing.Dict[str, typing.Tuple[peewee.Field, typing.List[peewee.Field]]] = None

    def __init__(
            self,
            fields: typing.Union[typing.List[str], typing.Dict[str, str]],
            **kwargs
    ):
        super().__init__(**kwargs)
        if isinstance(fields, list):
            self.fields = [
                (k, "contains") for k in fields
            ]
        else:
            try:
                self.fields = [
                    (k, OPERATORS[v]) for k, v in fields.items()
                ]
            except KeyError as e:
                key = str(e)
                raise TypeError(f"No such operator `{key}`.")

    def get_annotation(self, filterset):
        return Parameter(str, description=self.description, default=self.default)

    def get_concrete_filter(
            self,
            model: peewee.Model
    ) -> "Filter":
        candidates = PEEWEE_FIELD_REVERSE_MAPPING[CharFilter]
        field_and_joins = {}
        for name, operator in self.fields:
            field, joins = self.get_model_field_and_joins(model, name)
            field_and_joins[name] = field, joins
            key = field.rel_field if isinstance(field, ForeignKeyField) else type(field)
            # noinspection PyTypeHints
            if not issubclass(key, candidates):
                raise TypeError(
                    f"Filter `{self.__class__.__name__}` is not suitable for field `{key.__name__}`"
                )
        return self.clone(field_and_joins=field_and_joins)

    def apply(
            self,
            filterset,
            query: Query,
            value: str,
            context: typing.Any = None
    ) -> Query:
        where = None
        field_and_joins = self.field_and_joins
        for field_name, operator in self.fields:
            if field_and_joins is not None:
                field, joins = self.field_and_joins[field_name]
            else:
                field, joins = self.get_model_field_and_joins(query.model, field_name)
            if joins:
                query = self.ensure_join(query, joins)
            expr = getattr(field, operator)(value)
            if where is not None:
                where |= expr
            else:
                where = expr
        if where:
            query = query.where(where)
        return query
