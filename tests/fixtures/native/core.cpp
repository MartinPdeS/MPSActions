#include <pybind11/pybind11.h>

#ifdef MPS_FORTRAN_FIXTURE
extern "C" double mps_fortran_add(double left, double right);
#endif

PYBIND11_MODULE(_core, module) {
#ifdef MPS_FORTRAN_FIXTURE
    module.def("add", &mps_fortran_add);
#else
    module.def("add", [](double left, double right) { return left + right; });
#endif
}
