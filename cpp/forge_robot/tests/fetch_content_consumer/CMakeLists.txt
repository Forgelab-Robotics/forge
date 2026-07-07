cmake_minimum_required(VERSION 3.20)

project(forge_robot_fetch_content_consumer LANGUAGES CXX)

include(FetchContent)

if(NOT FORGE_FETCH_SOURCE_DIR)
  message(FATAL_ERROR "FORGE_FETCH_SOURCE_DIR must point at the forge repository root")
endif()

FetchContent_Declare(
  forge
  SOURCE_DIR ${FORGE_FETCH_SOURCE_DIR}
  SOURCE_SUBDIR cpp/forge_robot
)
FetchContent_MakeAvailable(forge)

add_executable(forge_robot_fetch_content_consumer main.cpp)
target_link_libraries(forge_robot_fetch_content_consumer PRIVATE forge_robot::forge_robot)
