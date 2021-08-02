
# pytest-ptera

This package enables the definition of various probes on a program, which can be activated using the `--probe` option. Probes are defined using [ptera](https://github.com/breuleux/ptera).


## Basic usage


Let's say you have the following bisect function:


```python
def bisect(arr, key):
    lo = -1
    hi = len(arr)
    while lo < hi - 1:
        mid = lo + (hi - lo) // 2
        if (elem := arr[mid]) > key:
            hi = mid
        else:
            lo = mid
    return lo + 1


def test_bisect():
    assert bisect(range(1, 100), 7) == 7
```


Assuming `bisect` is a function defined in `my_package/bisect.py`, you can inspect the values of `elem` with the following command:


```
$ pytest -rP --probe "/my_package.bisect/bisect > elem"
=========================== test session starts ===========================
platform darwin -- Python 3.9.5, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /Users/breuleuo/code/pytest-ptera
plugins: ptera-0.1.0, breakword-0.1.0
collected 1 item

tests/test_bisect.py .                                              [100%]

================================= PASSES ==================================
_______________________________ test_bisect _______________________________
-------------------------- Captured stdout call ---------------------------
{'elem': 50}
{'elem': 25}
{'elem': 12}
{'elem': 6}
{'elem': 9}
{'elem': 7}
{'elem': 8}
============================ 1 passed in 0.29s ============================
```


## Reusable probes

You can define named probes in `conftest.py` that do exactly what you want. For example, to reproduce the above probe:


```python
def probe_elem(reporter):
    prb = probing("/my_project.bisect/bisect > elem")
    prb.subscribe(print)
    return prb
```

Then you can use the probe's name with `--probe`:

```bash
$ pytest -rP --probe elem
...
```


### Metrics

You can use a probe to define metrics that will be summarized at the end, for instance counting the number of times `elem` is set for each test:


```python
def probe_hilo(reporter):
    prb = probing("/my_project.bisect/bisect > elem")
    prb = prb.pipe(op.getitem("elem"), op.count())
    prb.subscribe(reporter.metric(sort="desc", format="{:10}"))
    return prb
```

```
$ pytest tests/test_bisect.py --probe hilo
=========================== test session starts ===========================
platform darwin -- Python 3.9.5, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /Users/breuleuo/code/pytest-ptera
plugins: ptera-0.1.0, breakword-0.1.0
collected 1 item

tests/test_bisect.py .                                              [100%]

========================
Results for probe 'hilo'
========================
tests/test_bisect.py::test_bisect            7

============================ 1 passed in 0.29s ============================
```
