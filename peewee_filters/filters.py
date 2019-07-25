import inspect
import itertools
import peewee
import datetime
import decimal
from typesystem import String, Integer, Float, Decimal, Any, DateTime, Date, Time, Boolean


OPERATORS = {
    "eq": "__eq__",
    "lt": "__lt__",
    "gt": "__gt__",
    "lte": "__le__",
    "gte": "__gte__",
    "ne": "__ne__",
    "like": "__mod__",
    "ilike": "__pow__",
    "==": "__eq__",
    "<": "__lt__",
    "<=": "__le__",
    ">": "__gt__",
    ">=": "__ge__",
    "!=": "__ne__",
    "<<": "in_",
    ">>": "is_null",
    "%": "__mod__",
    "**": "__pow__"
}


class FilterBase:
    def __init__(self, field_name=None, description=""):
        self.field_name = field_name
        self.description = description

    def get_schema(self, _):
        raise NotImplementedError()

    def apply(self, filterset, queryset, value):
        raise NotImplementedError()

    def get_concrete_filter(self, _):
        return self


class Filter(FilterBase):
    def __init__(self, operator="__eq__", **kwargs):
        super().__init__(**kwargs)
        self.operator = OPERATORS.get(operator, operator)

    def get_schema(self, _):
        return Any(description=self.description)

    def apply(self, filterset, queryset, value):
        field = queryset.model._meta.fields[self.field_name]
        return queryset.where(getattr(field, self.operator)(value))

    def get_concrete_filter(self, model):
        if self.field_name not in model._meta.fields:
            raise TypeError(f"No such field {self.field_name}")
        key = type(model._meta.fields[self.field_name])
        mapping = PEEWEE_FIELD_MAPPING
        for cls in key.__mro__:
            if cls in mapping:
                suitable_class = mapping[cls]
                break
        else:
            raise TypeError(f"No suitable filter for field {key.__name__}")
        obj = suitable_class.__new__(suitable_class)
        obj.__dict__ = self.__dict__.copy()
        return obj


PRIMITIVES = {
    str: String,
    int: Integer,
    float: Float,
    decimal.Decimal: Decimal,
    bool: Boolean,
    datetime.datetime: DateTime,
    datetime.date: Date,
    datetime.time: Time
}


class MethodFilter(FilterBase):
    def __init__(self, method, **kwargs):
        super().__init__(**kwargs)
        self.method = method

    def get_schema(self, filterset_class):
        method = self.method if callable(self.method) else getattr(filterset_class, self.method)
        try:
            annotation = inspect.signature(method).parameters["value"].annotation
        except KeyError:
            raise TypeError(f"Method {method.__name__} is not suitable for filtering.")
        if annotation not in PRIMITIVES:
            return Any(description=self.description)
        return PRIMITIVES[annotation](description=self.description)

    def get_concrete_filter(self, _):
        return self

    def apply(self, filterset, queryset, value):
        if callable(self.method):
            method = self.method
        else:
            method = getattr(filterset, self.method)
        return method(queryset=queryset, field_name=self.field_name, value=value)


class _ConcreteFilter(Filter):
    validator = None

    def get_schema(self, _):
        return self.validator(description=self.description)

    def get_concrete_filter(self, model):
        if self.field_name not in model._meta.fields:
            raise TypeError(f"No such field {self.field_name}")
        candidates = PEEWEE_FIELD_REVERSE_MAPPING[self.__class__]
        key = type(model._meta.fields[self.field_name])
        # noinspection PyTypeHints
        if not issubclass(key, candidates):
            raise TypeError(f"Filter {self.__class__.__name__} is not suitable for field {key.__name__}")
        return self


class CharFilter(_ConcreteFilter):
    validator = String


class NumberFilter(_ConcreteFilter):
    validator = Float


class DateTimeFilter(_ConcreteFilter):
    validator = DateTime


class TimeFilter(_ConcreteFilter):
    validator = Time


class DateFilter(_ConcreteFilter):
    validator = Date


class BooleanFilter(_ConcreteFilter):
    validator = Boolean


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
    peewee.BooleanField: BooleanFilter
}


PEEWEE_FIELD_REVERSE_MAPPING = {
    k: tuple(x[0] for x in v)
    for k, v in itertools.groupby(
        sorted(list(PEEWEE_FIELD_MAPPING.items()), key=lambda x: id(x[1])),
        key=lambda x: x[1]
    )
}


class OffsetFilter(FilterBase):
    def get_schema(self, _):
        return Integer(minimum=0, description=self.description)

    def apply(self, _, queryset, value):
        return queryset.offset(value)


class LimitFilter(FilterBase):
    def __init__(self, default=1000, maximum=None, **kwargs):
        super().__init__(**kwargs)
        self.default = default
        self.maximum = maximum

    def get_schema(self, _):
        return Integer(minimum=0,
                       maximum=self.maximum,
                       default=self.default,
                       description=self.description)

    def apply(self, _, queryset, value):
        return queryset.limit(value)


class OrderingFilter(FilterBase):
    def __init__(self, fields, default=None, **kwargs):
        super().__init__(**kwargs)
        assert fields, "`fields` must be specified"
        self.fields = fields
        self.default = default

    def get_schema(self, _):
        kwargs = {}
        if self.default is not None:
            kwargs["default"] = ",".join(self.default)
        return String(description=self.description, **kwargs)

    def get_concrete_filter(self, model):
        for f in self.fields:
            if f not in model._meta.fields:
                raise TypeError(f"No such field {f}")
        return self

    def apply(self, _, queryset, value):
        order_by = []
        ordering = [f.strip() for f in value.split(",")]
        model_fields = queryset.model._meta.fields
        for field in ordering:
            if field.startswith("-"):
                desc = True
                field = field[1:]
            else:
                desc = False
            if field not in self.fields or field not in model_fields:
                continue
            field = model_fields[field]
            order_by.append(field.desc() if desc else field)
        return queryset.order_by_extend(*order_by)


class SearchingFilter(FilterBase):
    def __init__(self, fields, **kwargs):
        super().__init__(**kwargs)
        assert fields, "`fields` must be specified"
        self.fields = fields

    def get_schema(self, _):
        return String(description=self.description)

    def get_concrete_filter(self, model):
        candidates = PEEWEE_FIELD_REVERSE_MAPPING[CharFilter]
        for field_name in self.fields:
            if field_name.startswith("^") or field_name.startswith("="):
                field_name = field_name[1:]
            if field_name not in model._meta.fields:
                raise TypeError(f"No such field {field_name}")
            key = type(model._meta.fields[field_name])
            # noinspection PyTypeHints
            if not issubclass(key, candidates):
                raise TypeError(f"Filter {self.__class__.__name__} is not suitable for field {key.__name__}")
        return self

    def apply(self, _, queryset, value):
        where = None
        model_fields = queryset.model._meta.fields
        for field_name in self.fields:
            expr = None
            if field_name.startswith("^"):
                field_name = field_name[1:]
                if field_name in model_fields:
                    expr = model_fields[field_name].startswith(value)
            elif field_name.startswith("="):
                field_name = field_name[1:]
                if field_name in model_fields:
                    expr = model_fields[field_name] == value
            elif field_name in model_fields:
                expr = model_fields[field_name].contains(value)
            if expr:
                if where is not None:
                    where |= expr
                else:
                    where = expr
        if where:
            queryset = queryset.where(where)
        return queryset
