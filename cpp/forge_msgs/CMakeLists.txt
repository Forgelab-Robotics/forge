cmake_minimum_required(VERSION 3.20)

project(forge_msgs_cpp VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(Python3 COMPONENTS Interpreter)
find_package(Arrow CONFIG QUIET)

add_library(forge_msgs_cpp
  src/arrow.cpp
  src/audio.cpp
  src/control.cpp
  src/geometry.cpp
  src/forge_msgs.cpp
  src/perception.cpp
  src/sensor.cpp
  src/text.cpp
)
add_library(forge_msgs::forge_msgs ALIAS forge_msgs_cpp)

target_include_directories(forge_msgs_cpp
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

if(TARGET Arrow::arrow_shared)
  target_link_libraries(forge_msgs_cpp PUBLIC Arrow::arrow_shared)
elseif(TARGET Arrow::arrow_static)
  target_link_libraries(forge_msgs_cpp PUBLIC Arrow::arrow_static)
elseif(TARGET Arrow::arrow)
  target_link_libraries(forge_msgs_cpp PUBLIC Arrow::arrow)
else()
  if(NOT Python3_Interpreter_FOUND)
    message(FATAL_ERROR "Could not find Arrow CMake package or Python3 for pyarrow fallback")
  endif()
  execute_process(
    COMMAND ${Python3_EXECUTABLE} -c
      "import pyarrow, pathlib; print(pyarrow.get_include()); print(pyarrow.get_library_dirs()[0])"
    OUTPUT_VARIABLE PYARROW_ARROW_INFO
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE PYARROW_ARROW_RESULT
  )
  if(NOT PYARROW_ARROW_RESULT EQUAL 0)
    message(FATAL_ERROR "Could not find Arrow CMake package or import pyarrow for fallback")
  endif()
  string(REPLACE "\n" ";" PYARROW_ARROW_INFO_LIST "${PYARROW_ARROW_INFO}")
  list(GET PYARROW_ARROW_INFO_LIST 0 PYARROW_INCLUDE_DIR)
  list(GET PYARROW_ARROW_INFO_LIST 1 PYARROW_LIBRARY_DIR)
  find_library(PYARROW_ARROW_LIBRARY arrow HINTS ${PYARROW_LIBRARY_DIR} REQUIRED)
  target_include_directories(forge_msgs_cpp PUBLIC ${PYARROW_INCLUDE_DIR})
  target_link_libraries(forge_msgs_cpp PUBLIC ${PYARROW_ARROW_LIBRARY})
  set_target_properties(forge_msgs_cpp PROPERTIES
    BUILD_RPATH "${PYARROW_LIBRARY_DIR}"
    INSTALL_RPATH "${PYARROW_LIBRARY_DIR}"
  )
endif()

enable_testing()

add_executable(forge_msgs_cpp_tests tests/forge_msgs_tests.cpp)
target_link_libraries(forge_msgs_cpp_tests PRIVATE forge_msgs_cpp)
add_test(NAME forge_msgs_cpp_tests COMMAND forge_msgs_cpp_tests)

add_executable(forge_msgs_ipc_fixture tests/ipc_fixture.cpp)
target_link_libraries(forge_msgs_ipc_fixture PRIVATE forge_msgs_cpp)

if(Python3_Interpreter_FOUND)
  add_test(
    NAME forge_msgs_python_cpp_interop
    COMMAND Python3::Interpreter
      ${CMAKE_CURRENT_SOURCE_DIR}/tests/test_python_cpp_interop.py
      --driver $<TARGET_FILE:forge_msgs_ipc_fixture>
      --pythonpath ${CMAKE_CURRENT_SOURCE_DIR}/../../packages/msgs/src
  )
  set_tests_properties(forge_msgs_python_cpp_interop PROPERTIES SKIP_RETURN_CODE 77)
endif()
