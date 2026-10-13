#include <pybind11/pybind11.h>

PYBIND11_MODULE(_core, module) {
    module.def("add", [](double left, double right) { return left + right; });
}
