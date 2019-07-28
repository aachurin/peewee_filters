<p align="center">
    <em>Generic peewee filters.</em>
</p>

---

# Quickstart

Install peewee filters:

```bash
$ pip3 install peewee_generic_filters
```


```python
import peewee
import peewee_filters as filters


class Product(peewee.Model):
    title = peewee.CharField()
    description = peewee.CharField(null=True)
    price = peewee.IntegerField()


class Filter(filters.FilterSet):
    title = filters.Filter(operator="startswith")
    has_description = filters.MethodFilter("filter_description")
    price_min = filters.Filter(operator="ge")
    
    def filter_description(self, query, value: bool, **kwargs):    
        return query.where(
            Product.description.is_null(not value) | (
                (Product.description != "") if value else (Product.description == "")
            )
        )
    
    class Meta:
        model = Product


Filter({"title": "foo", "has_description": True}).apply(Product)
```

also it's possible to create `FilterSet` without binding concrete model.  

```python
class Filter(filters.FilterSet):
    title = filters.CharFilter(operator="startswith")
    has_description = filters.MethodFilter("filter_description")
    price_min = filters.NumberFilter(operator="ge")
    
    def filter_description(self, query, value: bool, **kwargs):    
        return query.where(
            Product.description.is_null(not value) | (
                (Product.description != "") if value else (Product.description == "")
            )
        )
```

In this case it's possible to use a FilterSet for multiple similar models.
But it is much slower than using a FilterSet with an explicit model.   

# Filters

### CharFilter
This filter does simple character matches, used with `CharField` and `TextField`.

### NumberFilter
Filters based on a numerical value, used with `IntegerField`, `FloatField`, and `DecimalField`.

### DateTimeFilter
Matches on a date and time. Used with `DateTimeField`.

### TimeFilter
Matches on a time. Used with `TimeField`.

### DateFilter
Matches on a date. Used with `DateField` by default.

### BooleanFilter
This filter matches a boolean, either `True` or `False`, used with `BooleanField`.

### UUIDFilter
This filter matches an UUID, used with `BinaryUUIDField`.

The following are the arguments that apply to all filters:

###### field_name
The name of the model field that is filtered against. 
If this argument is not provided, it defaults the filter’s attribute name on the `FilterSet` class.
Field names can traverse relationships by joining the related parts with separator (.). e.g., a product’s manufacturer.name.

###### description 
Filter description. Defaults to empty string.

###### operator
The field lookup that should be performed in the filter call.
Should be one of the following values: `eq`, `lt`, `gt`, `le`, `ge`, `ne`, `like`, `ilike`, `is_null`, `in`, `not_in`, `contains`, `startswith`, `endswith`, `regexp`, `iregexp`. 
Defaults to `eq`.

###### method
For `MethodFilter` only.
An argument that tells the filter how to handle the queryset.
It can accept either a callable or the name of a method on the `FilterSet`. 
The callable receives a `query`, the `field_name` of the model field to filter on, the `value` to filter with, and `context`.
It should return a filtered query. The parameter `value` of a callable should have annotation.

# Special filters
### SearchingFilter
Is used for searching in multiple fields. It accepts one additional argument:

######
 fields
The list of fields for searching.

### OffsetFilter
Specify value for OFFSET clause. 

### LimitFilter
Specify value for LIMIT clause.

It accepts two additional arguments:

###### default
Default value for LIMIT clause.
Defaults to `100`.

###### maximum
Maximum value for LIMIT clause.
Defaults to `None`.

### OrderingFilter
Enable queryset ordering. It accepts two additional arguments that are used to build the ordering choices:

###### fields
Is a mapping of {parameter name: model field name}. `fields` may also just be a list of strings. In this case, the field names simply double as the exposed parameter names.

###### default
Default ordering.

### SearchingFilter
Enable queryset searching. It accepts one additional argument:

###### fields
Is a mapping of {model field name: operator}. `fields` may also just be a list of strings.
In this case, the operator is `contains`. 
