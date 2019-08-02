import typing
import peewee
from . filters import Filter


class FilterSetOptions:
    def __init__(self, options=None):
        self.model = getattr(options, 'model', None)
        self.fields = getattr(options, 'fields', None)
        assert self.fields is None or isinstance(self.fields, (list, tuple)), (
            "`fields` option must be a list or a tuple"
        )


class FilterSetMeta(type):
    def __new__(cls, name, bases, attrs, **kwargs):
        parents = [b for b in bases if isinstance(b, FilterSetMeta)]
        if not parents:
            return super().__new__(cls, name, bases, attrs)
        for parent in parents:
            is_abstract = parent._meta.model is None
            assert is_abstract, "Only abstract bases is allowed"
        meta = FilterSetOptions(attrs.pop('Meta', None))
        attrs["_meta"] = meta
        declared_filters = cls.get_declared_filters(parents, attrs)
        if meta.model:
            declared_filters = cls.get_concrete_filters(declared_filters, meta.model)
        attrs["_declared_filters"] = declared_filters
        return super().__new__(cls, name, bases, attrs)

    @classmethod
    def get_declared_filters(cls, parents, attrs):
        filters = [
            (name, attrs.pop(name))
            for name, f in list(attrs.items())
            if isinstance(f, Filter)
        ]

        # Default the `filter.field_name` to the attribute name
        for name, f in filters:
            if getattr(f, 'field_name', None) is None:
                f.field_name = name

        # merge declared filters from base classes
        for parent in reversed(parents):
            if hasattr(parent, '_declared_filters'):
                filters = list(parent._declared_filters.items()) + filters
        return dict(filters)

    @classmethod
    def get_concrete_filters(cls, declared_filters, model):
        return {
            name: f.get_concrete_filter(model)
            for name, f in declared_filters.items()
        }


class FilterSet(metaclass=FilterSetMeta):
    _meta: FilterSetOptions = FilterSetOptions()
    _declared_filters: typing.Dict[str, Filter]

    def __init__(self, validated_params):
        self.validated_params = validated_params

    @classmethod
    def get_annotation(cls):
        return {
            name: f.get_annotation(cls)
            for name, f in cls._declared_filters.items()
        }

    def get_queryset(self, queryset):
        if queryset is None:
            queryset = self._meta.model
        assert queryset is not None, (
            f"'{self.__class__.__name__}' should either include a `model` option, "
            "or override the `get_queryset()` method."
        )
        return queryset

    def apply(self, queryset=None, context=None):
        queryset = self.get_queryset(queryset)
        if not isinstance(queryset, peewee.ModelSelect):
            queryset = queryset.select()
        params = self.validated_params
        for key, filter in self._declared_filters.items():
            value = params.get(key)
            if value is not None:
                queryset = filter.apply(self, queryset, value, context)
        return queryset
