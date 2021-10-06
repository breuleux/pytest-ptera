import sys
from collections import defaultdict

import pytest
from ptera import probing

formatting_info = {}
all_metrics = defaultdict(dict)


class Reporter:
    def __init__(self, name, item):
        self.name = name
        self.item = item

    def status_if_true(self, long, short=None, color="cyan", category=None):
        def do(x):
            if x:
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

        return do

    def metric(self, *, name=None, sort=None, format=None):
        def do(value):
            self.item.user_properties.append(
                (
                    "ptera_metric",
                    {
                        "name": name or self.name,
                        "value": value,
                        "sort": sort,
                        "format": format,
                    },
                )
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


_conftests = []
_cached_probes = {}


def make_display_probe(sel):
    pro = probing(sel)
    pro.display()
    return pro


def resolve_probe(sel):
    if sel in _cached_probes:
        return _cached_probes[sel]

    elif not isinstance(sel, str):
        result = {(): (getattr(sel, "__name__", "<probe>"), sel)}

    elif "." in sel or "/" in sel:
        result = {(): (sel, lambda _: make_display_probe(sel))}

    else:
        result = {}
        for cft in _conftests:
            fn = getattr(cft, f"probe_{sel}", None)
            if fn is not None:
                result[tuple(cft.__name__.split(".")[:-1])] = (sel, fn)
        if not result:
            raise NameError(f"Could not find probe '{sel}'")

    _cached_probes[sel] = result
    return result


def pytest_sessionstart(session):
    global _conftests
    _conftests = [
        mod
        for name, mod in sys.modules.items()
        if name.split(".")[-1] == "conftest"
    ]
    selectors = session.config.option.probe or []
    probes = []
    for sel in selectors:
        probes.append(resolve_probe(sel))

    session.ptera_probes = tuple(probes)


def pytest_runtest_setup(item):
    module_path = item.module.__name__.split(".")
    active_probes = []

    probes = item.session.ptera_probes
    for mark in item.iter_markers(name="useprobes"):
        probes = probes + tuple(resolve_probe(sel) for sel in mark.args)

    for pros in probes:
        for i in range(1, len(module_path) + 1):
            pth = tuple(module_path[:-i])
            if pth in pros:
                sel, pro = pros[pth]
                active_probes.append(pro(Reporter(sel, item)))
                break

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
            if name == "ptera_metric":
                name = value["name"]
                all_metrics[name][report.location] = value["value"]
                formatting_info[name] = value

        for name, value, *_ in report.user_properties:
            if name == "ptera_status":
                return (
                    value["category"],
                    value["short"],
                    (value["long"], {value.get("color", "white"): True}),
                )


def pytest_terminal_summary():
    for name, results in all_metrics.items():
        header = f"Results for probe '{name}'"
        print()
        print("=" * len(header))
        print(header)
        print("=" * len(header))
        info = formatting_info.get(name, None)
        results = [
            (f"{filename}::{test_name}", res)
            for (filename, _, test_name), res in results.items()
        ]
        if info["sort"] == "desc":
            results.sort(key=(lambda x: x[1]), reverse=True)
        elif info["sort"] == "asc":
            results.sort(key=(lambda x: x[1]))
        pad = max([len(loc) for loc, _ in results]) + 2
        format = info.get("format", None)
        for loc, result in results:
            if format:
                result = format.format(result)
            print(loc.ljust(pad), result)
