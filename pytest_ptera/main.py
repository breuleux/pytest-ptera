import inspect
import shutil
import sys
import warnings
from contextlib import contextmanager
from functools import partial
from itertools import chain

import pytest
from giving import SourceProxy
from ptera.utils import Named
from rx.internal.exceptions import SequenceContainsNoElementsError

_conftests = []
_summaries = {}


_terminal_width = shutil.get_terminal_size((80, 20)).columns


NO_ARGUMENT = Named("NO_ARGUMENT")


class Summary:
    def __init__(self):
        self._header = []
        self._lines = []
        self._footer = []

    def title(self, title):
        self.header(
            "~" * _terminal_width,
            title,
            "~" * _terminal_width,
        )
        self.footer("~" * _terminal_width)

    def header(self, *lines):
        self._header += lines

    def log(self, *lines):
        for line in lines:
            self._log(line)

    def _log(self, line):
        if isinstance(line, dict):
            if len(line) == 2 and "location" in line:
                d = dict(line)
                item = d.pop("location")
                (value,) = d.values()
                value = str(value)
                padding = _terminal_width - len(value)
                line = f"{item:{padding}}{value}"
        self._lines.append(line)

    def footer(self, *lines):
        self._footer += lines

    def dump(self):
        for line in chain(self._header, self._lines, self._footer):
            print(line)


def require_summary(metrics, summary_function):
    key = summary_function
    if summary_function not in _summaries:
        if inspect.isgeneratorfunction(summary_function):
            summary_function = contextmanager(summary_function)
        summary = Summary()
        rval = summary_function(metrics, summary)
        if hasattr(rval, "__enter__"):
            rval.__enter__()
            summary._exit = rval
        _summaries[key] = summary


class Reporter:
    def __init__(self, name, item):
        self.name = name
        self.item = item
        self.broadcast_stream = self.item.session.broadcast_stream

    def set_status(
        self,
        long,
        short=None,
        color="cyan",
        category=None,
    ):
        self.item.user_properties.append(
            (
                "ptera_status",
                {
                    "category": category or long.lower(),
                    "long": long,
                    "short": short or long[0],
                    "color": color,
                },
            )
        )

    def status(
        self,
        long,
        short=None,
        color="cyan",
        category=None,
        condition=lambda x: x is not False,
    ):
        done = False

        def do(x):
            nonlocal done
            if not done and (condition is None or condition(x)):
                self.set_status(
                    long=long, short=short, color=color, category=category
                )
                done = True

        return do

    def broadcast(self, key=None, **data):
        def do(value):
            if key is None:
                assert isinstance(value, dict) and len(value) == 1
                ((metric, value),) = value.items()
            else:
                metric = key

            if self.broadcast_stream:
                filename, _, testname = self.item.location
                self.broadcast_stream._push(
                    {
                        metric: value,
                        "location": f"{filename}::{testname}",
                    }
                )

        if key and not isinstance(key, str):
            raise TypeError("key argument should be a string")

        if data:
            if key is not None:
                raise TypeError(
                    "key should not be provided along with keyword arguments"
                )
            do(data)
        else:
            return do


def pytest_addoption(parser, pluginmanager):
    parser.addoption(
        "-P",
        "--probe",
        help="Probe selector for logging",
        action="append",
        default=None,
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "useprobes(*probes): use the specified probes"
    )


class FunctionFinder:
    def __init__(self, prefix, default=None):
        self.prefix = prefix
        self.default = default
        self.cache = {}

    def find(self, sel):
        if sel in self.cache:
            return self.cache[sel]

        elif not isinstance(sel, str):
            result = {(): sel}

        elif "." in sel or "/" in sel:
            if self.default is None:
                result = {}
            else:
                result = {(): partial(self.default, sel)}

        elif "," in sel:
            result = {}
            for sel in sel.split(","):
                result.update(self.find(sel))

        else:
            result = {}
            for cft in _conftests:
                fn = getattr(cft, f"{self.prefix}_{sel}", None)
                if fn is not None:
                    result[tuple(cft.__name__.split(".")[:-1])] = fn

        self.cache[sel] = result
        return result

    def resolve(self, sel, module_path):
        pros = self.find(sel)
        for i in range(1, len(module_path) + 1):
            pth = tuple(module_path[:-i])
            if pth in pros:
                return pros[pth]


def make_display_probe(sel, reporter):
    from ptera import probing

    pro = probing(sel)
    pro.display()
    return pro


_probe_finder = FunctionFinder(prefix="probe", default=make_display_probe)
_summary_finder = FunctionFinder(prefix="summary", default=None)


def pytest_sessionstart(session):
    global _conftests
    _conftests = [
        mod
        for name, mod in sys.modules.items()
        if name.split(".")[-1] == "conftest"
    ]
    session.ptera_probes = tuple(session.config.option.probe or ())
    session.broadcast_stream = SourceProxy()
    session.broadcast_stream.__enter__()


def pytest_runtest_setup(item):
    module_path = item.module.__name__.split(".")
    active_probes = []

    selectors = item.session.ptera_probes
    for mark in item.iter_markers(name="useprobes"):
        for arg in mark.args:
            if isinstance(arg, (list, tuple, set, frozenset)):
                selectors = selectors + tuple(arg)
            else:
                selectors = selectors + (arg,)

    selectors = list({sel: None for sel in selectors}.keys())

    active_probes = []
    for sel in selectors:
        probe_fn = _probe_finder.resolve(sel, module_path)
        summary_fn = _summary_finder.resolve(sel, module_path)
        if not probe_fn and not summary_fn:
            raise NameError(f"Could not find probe '{sel}'")
        if summary_fn:
            require_summary(item.session.broadcast_stream, summary_fn)
        if probe_fn:
            if inspect.isgeneratorfunction(probe_fn):
                probe_fn = contextmanager(probe_fn)
            probe = probe_fn(Reporter(sel, item))
            if not hasattr(probe, "__enter__"):
                raise TypeError(
                    "Probe function should be a generator or context manager"
                )
            active_probes.append(probe)

    for pro in active_probes:
        pro.__enter__()

    item._ptera_probes = active_probes


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    for pro in item._ptera_probes:
        try:
            pro.__exit__(None, None, None)
        except SequenceContainsNoElementsError:
            warnings.warn("A probe attempted a reduction with no elements")


def pytest_report_teststatus(report, config):
    if report.when == "call":
        for name, value, *_ in report.user_properties:
            if name == "ptera_status":
                return (
                    value["category"],
                    value["short"],
                    (value["long"], {value.get("color", "white"): True}),
                )


def pytest_sessionfinish(session, exitstatus):
    session.broadcast_stream.__exit__(None, None, None)


def pytest_terminal_summary():
    for summ in _summaries.values():
        if getattr(summ, "_exit", None):
            summ._exit.__exit__(None, None, None)
        summ.dump()
