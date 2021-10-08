import sys
from collections import defaultdict
from functools import partial
from itertools import chain

import pytest
from giving import ObservableProxy, SourceProxy

_conftests = []
_summaries = {}


class Summary:
    def __init__(self):
        self._header = []
        self._lines = []
        self._footer = []

    def header(self, *lines):
        self._header += lines

    def log(self, *lines):
        self._lines += lines

    def footer(self, *lines):
        self._footer += lines

    def dump(self):
        for line in chain(self._header, self._lines, self._footer):
            print(line)


def require_summary(metrics, summary_function):
    if summary_function not in _summaries:
        summary = Summary()
        summary_function(metrics, summary)
        _summaries[summary_function] = summary


class Reporter:
    def __init__(self, name, item):
        self.name = name
        self.item = item
        self.metrics_stream = self.item.session.metrics_stream

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
                done = True

        return do

    def metric(self, name=None):
        def do(value):
            if name is None:
                assert isinstance(value, dict) and len(value) == 1
                ((metric, value),) = value.items()
            else:
                metric = name

            if self.metrics_stream:
                filename, _, testname = self.item.location
                self.metrics_stream._push(
                    {
                        "metric": metric,
                        "value": value,
                        "location": f"{filename}::{testname}",
                    }
                )

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


def make_display_probe(sel):
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
    session.metrics_stream = SourceProxy()
    session.metrics_stream.__enter__()


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
            require_summary(item.session.metrics_stream, summary_fn)
        if probe_fn:
            probe = probe_fn(Reporter(sel, item))
            if not isinstance(probe, ObservableProxy):
                raise TypeError(
                    "Probe function should return an instance of probing()"
                )
            active_probes.append(probe)

    for pro in active_probes:
        pro.__enter__()

    item._ptera_probes = active_probes


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    yield
    for pro in item._ptera_probes:
        pro.__exit__(None, None, None)


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
    session.metrics_stream.__exit__(None, None, None)


def pytest_terminal_summary():
    for summ in _summaries.values():
        summ.dump()
