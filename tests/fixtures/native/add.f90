! Internal I/O exercises the Fortran runtime in a mixed-language extension.
function mps_fortran_add(left, right) bind(C) result(value)
    use iso_c_binding
    implicit none
    real(c_double), value :: left, right
    real(c_double) :: value
    character(len=64) :: buffer

    write(buffer, *) left + right
    read(buffer, *) value
end function mps_fortran_add
