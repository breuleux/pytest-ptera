
# pytest-ptera

This package enables the definition of various probes on a program, which can be activated using the `--probe` option. Probes are defined using [ptera](https://github.com/breuleux/ptera) (**[Documentation](https://ptera.readthedocs.io/en/latest/index.html)**).

The two main purposes of `pytest-ptera` are:

1. Inspect variables inside the program and complex metrics about them.
2. Define assertions deep into the core of the program.

For example, if a function expects to receive a sorted list, you can define a probe that verifies that the list is sorted whenever that function is called and use that probe on any existing test that might trigger that execution path.

Or if you need to verify some invariant that `x > y` in some function, you can also do that easily.


## Basic CLI usage


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

Tip: if you want some help about what to type after `--probe`, try this:

```python
>>> from ptera import refstring
>>> from my_package import bisect
>>> refstring(bisect)
"/my_package.bisect/bisect"
```

Then you just write `> varname` if you want to display `varname`. There are a lot more things you can do, including displaying multiple variables at the same time. [For more information, see Ptera's documentation](https://ptera.readthedocs.io/en/latest/guide.html#probing)


## Reusable probes

You can define named probes in `conftest.py` that do exactly what you want. For example, to reproduce the above probe, put the following code in `conftest.py`:


```python
from ptera import probing

def probe_elem(reporter):
    with probing("/my_project.bisect/bisect > elem").print():
        yield
```

Then you can use the probe's name with `--probe`:

```bash
$ pytest -rP --probe elem
...
```


### Assertions

Another great use for probes is to check that certain conditions hold at specific points of the execution. For example, if you use `bisect` deep in your business logic to find things in a list that should always be ordered, you can use a probe to verify that this is indeed always the case. You would need to write something like this in `conftest.py`:

```python
from ptera import probing

def _unordered(xs):
    return any(x > y for x, y in zip(xs[:-1], xs[1:]))

def probe_ordered(reporter):
    with probing("/my_project.bisect/bisect > arr") as probe:
        probe["arr"].filter(_unordered).fail("List is unordered: {}")
        yield
```

If the pipeline interface is not fully intuitive to you, here is an alternative way to write the above:

```python
def probe_ordered_2(reporter):
    with probing("/my_project.bisect/bisect > arr") as probe:
        @probe.subscribe
        def check(entry):
            if unordered(entry["arr"]):
                raise Exception("List is not ordered!")
        yield
```

The first version is a bit more practical with the `--pdb` flag as it should bring you directly in the right spot. The second will require you to go up the stack for a bit.

You can use the flag `--probe ordered` to activate the probe above, but you can also activate it on specific tests with the `useprobes` mark:

```python
@pytest.mark.useprobes("ordered")
def test_bisect_unordered():
    bisect([1, 6, 30, 7], 18)
```


### Fixtures

If you only want to apply a probe on certain tests, you can just define it as a fixture and use it like any other fixture:

```python
@pytest.fixture
def check_ordered():
    with probing("/my_project.bisect/bisect > arr") as probe:
        probe["arr"].filter(_unordered).fail("List is unordered: {}")
        yield

@pytest.mark.usefixtures("check_ordered")
def test_bisect_unordered():
    bisect([1, 6, 30, 7], 18)
```

And of course if you only want to use it for a single test you can just do it inside the test directly:

```python
def test_bisect_unordered():
    # Note: You can just write "bisect > arr" if bisect is in the current namespace
    with probing("bisect > arr") as probe:
        probe["arr"].filter(_unordered).fail("List is unordered: {}")
        bisect([1, 6, 30, 7], 18)
```

Note: the fixture and direct methods do not require `ptera_pytest`, only `ptera`.


### Summaries

You can use a probe to define metrics that will be summarized at the end:

* Define both `summary_xyz` and `probe_xyz`.
* `summary_xyz` takes the metrics stream and a Summary object.
* `probe_xyz` broadcasts metrics for each test with `reporter.broadcast`.

The broadcasted metrics are a stream of dictionaries like `{metric_name: value, "location": test_location_string}`. It is basically a single stream merging everything every test has broadcasted.

For instance let's say we want to count the number of times `elem` is set for each test, order in descending order, and display the top 10:

```python
def summary_countelem(metrics, summary):
    summary.title("Results for probe 'countelem'")
    metrics \
        .where("countelem") \
        .top(n=10, key="countelem") \
        >> summary.log

def probe_countelem(reporter):
    with probing("/my_project.bisect/bisect > elem")["elem"] as probe:
        probe.count() >> reporter.broadcast("countelem")
        yield
```

```
$ pytest tests/test_bisect.py --probe countelem
=========================== test session starts ===========================
platform darwin -- Python 3.9.5, pytest-6.2.4, py-1.10.0, pluggy-0.13.1
rootdir: /Users/breuleuo/code/pytest-ptera
plugins: ptera-0.1.0, breakword-0.1.0
collected 1 item

tests/test_bisect.py .                                              [100%]

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Results for probe 'countelem'
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
tests/test_bisect.py::test_bisect                                         7
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

============================ 1 passed in 0.29s ============================
```

If you find the interface a bit difficult, you can also write the summary like this:

```python
def summary_countelem(metrics, summary):
    results = metrics.where("countelem").accum()

    yield

    print("Results for probe 'countelem'")
    for entry in sorted(results, key=lambda result: result["countelem"]):
        print("{location:100} {countelem:>10}".format(entry))
```


### Custom status

Lastly, a probe can set a custom status for the result of a test, which lets you see at a glance which tests trigger certain conditions. For example:

```python
# in conftest.py

def probe_countelem2(reporter):
    with probing("/my_project.bisect/bisect > elem") as probe:
        probe = probe["elem"].count().some(lambda x: x > 5)
        probe >> reporter.status("WOW", short="!", color="red", category="surprises")

        yield

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
