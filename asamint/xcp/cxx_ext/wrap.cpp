
#include <pybind11/pybind11.h>

#include <functional>
#include <map>
#include <string>

#include "rekorder.hpp"

namespace py = pybind11;

using namespace pybind11::literals;


PYBIND11_MODULE(animal, m) {
    py::class_<XcpLogFileReader>(m, "XcpLogFileReader")
        .def(py::init<const std::string&>())

    ;
#if 0
    py::class_<Animal, PyAnimal /* <--- trampoline*/>(m, "Animal")
        .def(py::init<>())
        .def("go", &Animal::go);

    py::class_<Dog, Animal>(m, "Dog")
        .def(py::init<>());
#endif

// the Classes are then registered with pybind11 using:

//    py::class_<Animal, PyAnimal<>> (m, "Animal").def(py::init<>());
//    py::class_<Dog, Animal, PyDog<>> (m, "Dog").def(py::init<>());
//    py::class_<Husky, Dog, PyDog<Husky>> (m, "Husky").def(py::init<>());
}

