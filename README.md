
# pytest-ptera

This package enables the definition of various probes on a program, which can be activated using the `--probe` option. Probes are defined using [ptera](https://github.com/breuleux/ptera).

The two main purposes of `pytest-ptera` are:

1. Inspect variables inside the program and complex metrics about them.
2. Define assertions deep into the core of the program.

For example, if a function expects to receive a sorted list, you can define a probe that verifies that the list is sorted whenever that function is called and use that probe on any existing test that might trigger that execution path.

Or if you need to verify some invariant that `x > y` in some function, you can also do that easily.


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
elem: 50
elem: 25
elem: 12
elem: 6
elem: 9
elem: 7
elem: 8
============================ 1 passed in 0.29s ============================
```


## Reusable probes

You can define named probes in `conftest.py` that do exactly what you want. For example, to reproduce the above probe, put the following code in `conftest.py`:


```python
from ptera import probing

def probe_elem(reporter):
    return probing("/my_project.bisect/bisect > elem").print()
```

Then you can use the probe's name with `--probe`:

```bash
$ pytest -rP --probe elem
...
```


### Assertions

Another great use for probes is to assert that certain conditions hold at specific points of the execution. For example, if you use `bisect` deep in your business logic to find things in a list that should always be ordered, you can use a probe to verify that this is indeed always the case. You would need to write something like this in `conftest.py`:

```python
from ptera import probing

def probe_ordered(reporter):
    def unordered(xs):
        return any(x > y for x, y in zip(xs[:-1], xs[1:]))

    probe = probing("/my_project.bisect/bisect > arr")
    probe.filter(unordered).fail("List is unordered: {}")
    return probe
```

Again, you can use the flag `--probe ordered` to activate it, but you can also activate it on specific tests with the `useprobes` mark:


```python
@pytest.mark.useprobes("ordered")
def test_bisect_unordered():
    bisect([1, 6, 30, 7], 18)
```

Note: if you have a direct handle to `probe_ordered`, you can pass it by reference instead of by name with `pytest.mark.useprobes([probe_ordered])`, but don't forget to put it in a list, otherwise `mark` thinks it is the test function to decorate.

Note 2: this is compatible with the `--pdb` flag, so you can easily debug offending test cases.


### Summaries

You can use a probe to define metrics that will be summarized at the end:

* Define both `summary_xyz` and `probe_xyz`.
* `summary_xyz` takes the metrics stream and a Summary object.
* `probe_xyz` sets metrics for each test with `reporter.metric`.

The metrics are a stream of dictionaries like `{"metric": name, "value": value, "location": test_location_string}`.

For instance let's say we want to count the number of times `elem` is set for each test, order in descending order, and display the top 10:

```python
def summary_countelem(metrics, summary):
    summary.header(
        "=============================",
        "Results for probe 'countelem'",
        "=============================",
    )
    summary.footer(
        "=============================",
    )
    metrics \
        .where(metric="countelem") \
        .top(n=10, key=lambda entry: entry["value"]) \
        .format("{location:50} {value:>10}") \
        >> summary.log

def probe_countelem(reporter):
    prb = probing("/my_project.bisect/bisect > elem")["elem"].count()
    prb >> reporter.metric("countelem")
    return prb
```

```
$ pytest tests/test_bisect.py --probe countelem
=========================== test session starts ===========================
platform darwin -- Python 3.9.5, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /Users/breuleuo/code/pytest-ptera
plugins: ptera-0.1.0, breakword-0.1.0
collected 1 item

tests/test_bisect.py .                                              [100%]

=============================
Results for probe 'countelem'
=============================
tests/test_bisect.py::test_bisect            7

============================ 1 passed in 0.29s ============================
```


### Custom status

Lastly, a probe can set a custom status for the result of a test, which lets you see at a glance which tests trigger certain conditions. For example:

```python
# in conftest.py

def probe_countelem2(reporter):
    prb = probing("/my_project.bisect/bisect > elem")
    prb = prb["elem"].count().some(lambda x: x > 5)
    prb >> reporter.status("WOW", short="!", color="red", category="surprises")
    return prb


# in test_bisect.py

def test_1():
    assert bisect(list(range(1, 10)), 7) == 7

def test_2():
    assert bisect(list(range(1, 100)), 7) == 7
```

```
$ pytest tests/test_bisect.py --probe countelem2
================================== test session starts ===================================
platform darwin -- Python 3.9.5, pytest-6.2.5, py-1.10.0, pluggy-1.0.0
rootdir: /Users/olivier/code/pytest-ptera
plugins: ptera-0.1.1, breakword-0.1.0
collected 2 items

tests/test_bisect.py .!                                                            [100%]

============================= 1 passed, 1 surprises in 0.19s ============================
```

All arguments to `reporter.status` are optional save for the first.


## Suggestions

```python

def probe_call_myf():
    """Give status YES to any test that calls myf() (and gets a result)."""
    probe = probing("/my_package/myf() as value")
    probe.some() >> reporter.status("YES", short="!", color="red")
    return probe

```

