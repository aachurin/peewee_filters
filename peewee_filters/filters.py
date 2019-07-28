import inspect
import itertools
import peewee
import datetime
import decimal
import typing
import uuid
from peewee import ForeignKeyField, BackrefAccessor
from typesystem import (
    Field,
    String,
    Integer,
    Float,
    Decimal,
    Any,
    DateTime,
    Date,
    Time,
    Boolean,
    Array
)

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
    "^": "startswith",
    "startswith": "startswith",
    "$": "endswith",
    "endswith": "endswith",
    "regexp": "regexp",
    "iregexp": "iregexp"
}


class Filter:

    field_and_joins: typing.Tuple[peewee.Field, typing.List[peewee.Field]] = None

    def __init__(
            self,
            field_name: str = None,
            description: str = "",
            operator: str = "eq"
    ):
        self.description = description
        self.field_name = field_name
        try:
            self.operator = OPERATORS[operator]
        except KeyError:
            raise TypeError(f"No such operator `{operator}`.")

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

    def get_schema(self, filterset) -> Field:
        raise TypeError(f"Not a concrete filter.")

    def clone(self, cls=None, **kwargs):
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


PRIMITIVES = {
    str: String,
    int: Integer,
    float: Float,
    decimal.Decimal: Decimal,
    bool: Boolean,
    datetime.datetime: DateTime,
    datetime.date: Date,
    datetime.time: Time,
    uuid.UUID: lambda **kwargs: String(format="uuid", **kwargs)
}


class MethodFilter(Filter):
    def __init__(self, method: typing.Union[typing.Callable, str], **kwargs):
        super().__init__(**kwargs)
        self.method = method

    def get_schema(self, filterset) -> Field:
        method = self.method if callable(self.method) else getattr(filterset, self.method)
        try:
            t = inspect.signature(method).parameters["value"].annotation
        except KeyError:
            raise TypeError(f"Method `{method.__name__}` is not suitable for filtering.")

        if t in PRIMITIVES:
            return PRIMITIVES[t](description=self.description)

        o = getattr(t, "__origin__", t)
        if issubclass(o, (typing.Sequence, typing.Set)):
            unique_items = issubclass(o, typing.Set)
            if hasattr(t, "__args__") and not t._special:
                try:
                    items = PRIMITIVES[t.__args__[0]]
                except KeyError:
                    raise TypeError(f"Annotation `{t}` is not supported.")
                return Array(items=items(), unique_items=unique_items, description=self.description)
            else:
                return Array(unique_items=unique_items, description=self.description)
        elif issubclass(o, typing.Tuple):
            if hasattr(t, "__args__") and not t._special:
                if len(t.__args__) == 2 and t.__args__[1] is ...:
                    try:
                        items = PRIMITIVES[t.__args__[0]]
                    except KeyError:
                        raise TypeError(f"Annotation `{t}` is not supported.")
                    return Array(items=items(), description=self.description)
                else:
                    try:
                        items = [PRIMITIVES[x]() for x in t.__args__]
                    except KeyError:
                        raise TypeError(f"Annotation `{t}` is not supported.")
                    return Array(items=items, description=self.description)
            else:
                return Array(description=self.description)
        else:
            return Any(description=self.description)

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
    validator = None

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

    def get_schema(self, filterset) -> Field:
        if self.operator == "is_null":
            return Boolean(description=self.description)
        elif self.operator in ("in_", "not_in"):
            return Array(items=self.validator(), description=self.description)
        return self.validator(description=self.description)

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
        return query.where(getattr(field, self.operator)(value))


class CharFilter(ConcreteFilter):
    validator = String

    def check_operator(self):
        pass


class NumberFilter(ConcreteFilter):
    validator = Float


class DateTimeFilter(ConcreteFilter):
    validator = DateTime


class TimeFilter(ConcreteFilter):
    validator = Time


class DateFilter(ConcreteFilter):
    validator = Date


class BooleanFilter(ConcreteFilter):
    validator = Boolean


class UUIDFilter(ConcreteFilter):
    def validator(self, **kwargs):
        return String(format="uuid", **kwargs)


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
    def get_schema(self, filterset) -> Field:
        return Integer(minimum=0, description=self.description)

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
        return query.offset(value)


class LimitFilter(Filter):
    def __init__(self, default=100, maximum=None, **kwargs):
        super().__init__(**kwargs)
        self.default = default
        self.maximum = maximum

    def get_schema(self, filterset) -> Field:
        return Integer(minimum=0,
                       maximum=self.maximum,
                       default=self.default,
                       description=self.description)

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
        return query.limit(value)


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

    def get_schema(self, filterset) -> Field:
        kwargs = {}
        if self.default is not None:
            kwargs["default"] = self.default
        return Array(items=String(), description=self.description, **kwargs)

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
            value: typing.Any,
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

    def get_schema(self, filterset) -> Field:
        return String(description=self.description)

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
            value: typing.Any,
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
