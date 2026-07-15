set(DORA_ROOT_DIR "" CACHE PATH "Path to the root of a local Dora v0.4.1 checkout")

set(dora_c_include_dir "${CMAKE_CURRENT_BINARY_DIR}/include/c")
set(dora_cxx_include_dir "${CMAKE_CURRENT_BINARY_DIR}/include/cxx")
set(node_bridge "${CMAKE_CURRENT_BINARY_DIR}/node_bridge.cc")
set(operator_bridge "${CMAKE_CURRENT_BINARY_DIR}/operator_bridge.cc")
set(dora_bridge_copy_script "${CMAKE_CURRENT_BINARY_DIR}/copy_dora041_bridges.cmake")

file(WRITE ${dora_bridge_copy_script} [=[
file(GLOB node_bridge_sources "${DORA_TARGET_DIR}/debug/build/dora-node-api-cxx-*/out/cxxbridge/sources/dora-node-api-cxx/src/lib.rs.cc")
file(GLOB node_bridge_headers "${DORA_TARGET_DIR}/debug/build/dora-node-api-cxx-*/out/cxxbridge/include/dora-node-api-cxx/src/lib.rs.h")
file(GLOB operator_bridge_sources "${DORA_TARGET_DIR}/debug/build/dora-operator-api-cxx-*/out/cxxbridge/sources/dora-operator-api-cxx/src/lib.rs.cc")
file(GLOB operator_bridge_headers "${DORA_TARGET_DIR}/debug/build/dora-operator-api-cxx-*/out/cxxbridge/include/dora-operator-api-cxx/src/lib.rs.h")

list(LENGTH node_bridge_sources node_bridge_source_count)
list(LENGTH node_bridge_headers node_bridge_header_count)
list(LENGTH operator_bridge_sources operator_bridge_source_count)
list(LENGTH operator_bridge_headers operator_bridge_header_count)
if(node_bridge_source_count EQUAL 0 OR node_bridge_header_count EQUAL 0 OR operator_bridge_source_count EQUAL 0 OR operator_bridge_header_count EQUAL 0)
  message(FATAL_ERROR "Could not find Dora v0.4.1 CXX bridge outputs in ${DORA_TARGET_DIR}")
endif()

list(GET node_bridge_sources 0 node_bridge_source)
list(GET node_bridge_headers 0 node_bridge_header)
list(GET operator_bridge_sources 0 operator_bridge_source)
list(GET operator_bridge_headers 0 operator_bridge_header)

file(MAKE_DIRECTORY "${DORA_CXX_INCLUDE_DIR}")
file(MAKE_DIRECTORY "${DORA_C_INCLUDE_DIR}")
file(COPY_FILE "${node_bridge_source}" "${NODE_BRIDGE}")
file(COPY_FILE "${node_bridge_header}" "${DORA_CXX_INCLUDE_DIR}/dora-node-api.h")
file(COPY_FILE "${operator_bridge_source}" "${OPERATOR_BRIDGE}")
file(COPY_FILE "${operator_bridge_header}" "${DORA_CXX_INCLUDE_DIR}/dora-operator-api.h")
file(COPY "${DORA_SOURCE_DIR}/apis/c/node" DESTINATION "${DORA_C_INCLUDE_DIR}")
file(COPY "${DORA_SOURCE_DIR}/apis/c/operator" DESTINATION "${DORA_C_INCLUDE_DIR}")
]=])

include(ExternalProject)

if(DORA_ROOT_DIR)
  ExternalProject_Add(Dora
    SOURCE_DIR ${DORA_ROOT_DIR}
    BUILD_IN_SOURCE TRUE
    CONFIGURE_COMMAND ""
    BUILD_COMMAND
      cargo build --package dora-node-api-c &&
      cargo build --package dora-operator-api-c &&
      cargo build --package dora-node-api-cxx &&
      cargo build --package dora-operator-api-cxx
    INSTALL_COMMAND ""
  )

  add_custom_command(
    OUTPUT ${node_bridge} ${dora_cxx_include_dir} ${operator_bridge} ${dora_c_include_dir}
    WORKING_DIRECTORY ${DORA_ROOT_DIR}
    DEPENDS Dora
    COMMAND ${CMAKE_COMMAND}
      -DDORA_TARGET_DIR=${DORA_ROOT_DIR}/target
      -DDORA_SOURCE_DIR=${DORA_ROOT_DIR}
      -DDORA_CXX_INCLUDE_DIR=${dora_cxx_include_dir}
      -DDORA_C_INCLUDE_DIR=${dora_c_include_dir}
      -DNODE_BRIDGE=${node_bridge}
      -DOPERATOR_BRIDGE=${operator_bridge}
      -P ${dora_bridge_copy_script}
  )

  set(dora_link_dirs ${DORA_ROOT_DIR}/target/debug)
else()
  ExternalProject_Add(Dora
    PREFIX ${CMAKE_CURRENT_BINARY_DIR}/dora
    GIT_REPOSITORY https://github.com/dora-rs/dora.git
    GIT_TAG v0.4.1
    BUILD_IN_SOURCE TRUE
    CONFIGURE_COMMAND ""
    BUILD_COMMAND
      cargo build --package dora-node-api-c --target-dir ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target &&
      cargo build --package dora-operator-api-c --target-dir ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target &&
      cargo build --package dora-node-api-cxx --target-dir ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target &&
      cargo build --package dora-operator-api-cxx --target-dir ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target
    INSTALL_COMMAND ""
  )

  add_custom_command(
    OUTPUT ${node_bridge} ${dora_cxx_include_dir} ${operator_bridge} ${dora_c_include_dir}
    WORKING_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora
    DEPENDS Dora
    COMMAND ${CMAKE_COMMAND}
      -DDORA_TARGET_DIR=${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target
      -DDORA_SOURCE_DIR=${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora
      -DDORA_CXX_INCLUDE_DIR=${dora_cxx_include_dir}
      -DDORA_C_INCLUDE_DIR=${dora_c_include_dir}
      -DNODE_BRIDGE=${node_bridge}
      -DOPERATOR_BRIDGE=${operator_bridge}
      -P ${dora_bridge_copy_script}
  )

  set(dora_link_dirs ${CMAKE_CURRENT_BINARY_DIR}/dora/src/Dora/target/debug)
endif()

set_source_files_properties(${node_bridge} ${operator_bridge} PROPERTIES GENERATED TRUE)
add_custom_target(Dora_c DEPENDS ${dora_c_include_dir})
add_custom_target(Dora_cxx DEPENDS ${node_bridge} ${operator_bridge} ${dora_cxx_include_dir})
