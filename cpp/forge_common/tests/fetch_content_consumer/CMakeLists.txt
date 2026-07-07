cmake_minimum_required(VERSION 3.20)

project(forge_common_fetch_content_consumer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(FetchContent)

if(NOT DEFINED FORGE_FETCH_SOURCE_DIR)
  message(FATAL_ERROR "FORGE_FETCH_SOURCE_DIR must point to the forge repository root")
endif()

set(FORGE_COMMON_CPP_BUILD_TESTS OFF CACHE BOOL "" FORCE)

FetchContent_Declare(
  forge
  SOURCE_DIR "${FORGE_FETCH_SOURCE_DIR}"
  SOURCE_SUBDIR cpp/forge_common
)
FetchContent_MakeAvailable(forge)

add_executable(forge_common_fetch_content_consumer main.cpp)
target_link_libraries(forge_common_fetch_content_consumer PRIVATE forge_common::forge_common)
