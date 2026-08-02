cmake_minimum_required(VERSION 3.20)

project(forge_robot_cpp VERSION 1.0.0 LANGUAGES CXX)

find_package(Python3 COMPONENTS Interpreter)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(FORGE_ROBOT_CPP_BUILD_TESTS "Build C++ forge_robot tests" ${PROJECT_IS_TOP_LEVEL})
option(FORGE_ROBOT_CPP_WITH_DORA "Build the Dora C++ robot node runner" OFF)
set(DORA_CXX_BRIDGE_SOURCE "" CACHE FILEPATH "Path to a pre-generated Dora C++ node bridge source")

if(NOT TARGET forge_msgs::forge_msgs)
  add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../forge_msgs ${CMAKE_CURRENT_BINARY_DIR}/forge_msgs)
endif()

if(NOT TARGET forge_common::forge_common)
  add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../forge_common ${CMAKE_CURRENT_BINARY_DIR}/forge_common)
endif()

set(FORGE_ROBOT_CPP_SOURCES
  src/actuator_spec.cpp
  src/arrow_validation.cpp
  src/locomotion_spec.cpp
)

if(FORGE_ROBOT_CPP_WITH_DORA)
  if(NOT (DORA_CXX_INCLUDE_DIR AND DORA_CXX_LIBRARY))
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/Dora041Targets.cmake)
    set(DORA_CXX_INCLUDE_DIR ${dora_cxx_include_dir})
    set(DORA_CXX_LIBRARY dora_node_api_cxx)
    set(DORA_CXX_BRIDGE_SOURCE ${node_bridge})
  elseif(NOT DORA_CXX_BRIDGE_SOURCE)
    message(FATAL_ERROR
      "Pre-generated Dora CXX artifacts require DORA_CXX_BRIDGE_SOURCE. "
      "Omit DORA_CXX_INCLUDE_DIR/DORA_CXX_LIBRARY to use the built-in Dora v0.4.1 helper."
    )
  endif()
  list(APPEND FORGE_ROBOT_CPP_SOURCES src/node_runner.cpp)
  if(DORA_CXX_BRIDGE_SOURCE)
    list(APPEND FORGE_ROBOT_CPP_SOURCES ${DORA_CXX_BRIDGE_SOURCE})
  endif()
endif()

add_library(forge_robot_cpp ${FORGE_ROBOT_CPP_SOURCES})
add_library(forge_robot::forge_robot ALIAS forge_robot_cpp)

target_include_directories(forge_robot_cpp
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
    $<INSTALL_INTERFACE:include>
)

target_link_libraries(forge_robot_cpp
  PUBLIC
    forge_msgs::forge_msgs
    forge_common::forge_common
)

if(FORGE_ROBOT_CPP_WITH_DORA)
  if(NOT DORA_CXX_INCLUDE_DIR)
    message(FATAL_ERROR "FORGE_ROBOT_CPP_WITH_DORA requires DORA_CXX_INCLUDE_DIR")
  endif()
  if(NOT DORA_CXX_LIBRARY)
    message(FATAL_ERROR "FORGE_ROBOT_CPP_WITH_DORA requires DORA_CXX_LIBRARY")
  endif()
  if(TARGET Dora_cxx)
    add_dependencies(forge_robot_cpp Dora_cxx)
    target_link_directories(forge_robot_cpp PUBLIC ${dora_link_dirs})
  endif()
  target_compile_definitions(forge_robot_cpp PUBLIC FORGE_ROBOT_CPP_WITH_DORA=1)
  target_include_directories(forge_robot_cpp PUBLIC ${DORA_CXX_INCLUDE_DIR})
  target_link_libraries(forge_robot_cpp PUBLIC ${DORA_CXX_LIBRARY})
endif()

if(FORGE_ROBOT_CPP_BUILD_TESTS)
  enable_testing()

  add_executable(forge_robot_cpp_tests tests/robot_tests.cpp)
  target_link_libraries(forge_robot_cpp_tests PRIVATE forge_robot_cpp)
  add_test(NAME forge_robot_cpp_tests COMMAND forge_robot_cpp_tests)

  if(FORGE_ROBOT_CPP_WITH_DORA)
    add_executable(forge_robot_dora_runner_compile tests/dora_runner_compile.cpp)
    target_link_libraries(forge_robot_dora_runner_compile PRIVATE forge_robot_cpp)
  endif()

  set(FORGE_ROBOT_CPP_CONSUMER_BUILD_DIR ${CMAKE_CURRENT_BINARY_DIR}/fetch_content_consumer)
  set(FORGE_ROBOT_CPP_CONSUMER_PYTHON_ARGS)
  if(Python3_Interpreter_FOUND)
    list(APPEND FORGE_ROBOT_CPP_CONSUMER_PYTHON_ARGS
      -DPython3_EXECUTABLE=${Python3_EXECUTABLE}
    )
  endif()
  add_test(
    NAME forge_robot_fetch_content_consumer_configure
    COMMAND ${CMAKE_COMMAND}
      -S ${CMAKE_CURRENT_SOURCE_DIR}/tests/fetch_content_consumer
      -B ${FORGE_ROBOT_CPP_CONSUMER_BUILD_DIR}
      -G ${CMAKE_GENERATOR}
      ${FORGE_ROBOT_CPP_CONSUMER_PYTHON_ARGS}
      -DFORGE_FETCH_SOURCE_DIR=${CMAKE_CURRENT_SOURCE_DIR}/../..
  )
  add_test(
    NAME forge_robot_fetch_content_consumer_build
    COMMAND ${CMAKE_COMMAND} --build ${FORGE_ROBOT_CPP_CONSUMER_BUILD_DIR}
  )
  set_tests_properties(
    forge_robot_fetch_content_consumer_build
    PROPERTIES DEPENDS forge_robot_fetch_content_consumer_configure
  )
endif()
