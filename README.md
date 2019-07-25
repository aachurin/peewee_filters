<p align="center">
    <em>Generic peewee filters, for Python 3.</em>
</p>

---

# Quickstart

Install peewee_filters:

```bash
$ pip3 install peewee_filters
```


```python
import peewee_filters as filters


class Filter(filters.FilterSet):
    title = filters.CharField(operator="startswith")


Filter({"title": "foo"}).apply(Bar.select())

```
