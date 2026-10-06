cmake_minimum_required(VERSION 3.25.2)

project(RouteProof VERSION 0.1.0 LANGUAGES CXX)

include(cmake/Dependencies.cmake)

set(YAML_CPP_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(YAML_CPP_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(YAML_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(PICOSHA2_TEST OFF CACHE BOOL "" FORCE)
set(PICOSHA2_EXAMPLE OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(yaml-cpp nlohmann_json PicoSHA2)

if(NOT CMAKE_GENERATOR STREQUAL "Ninja")
    message(FATAL_ERROR "RouteProof's build contract uses the Ninja generator; configure with a checked-in CMake preset")
endif()

find_program(ROUTEPROOF_NINJA_EXECUTABLE NAMES ninja REQUIRED)
execute_process(
    COMMAND "${ROUTEPROOF_NINJA_EXECUTABLE}" --version
    OUTPUT_VARIABLE ROUTEPROOF_NINJA_VERSION
    OUTPUT_STRIP_TRAILING_WHITESPACE
    RESULT_VARIABLE ROUTEPROOF_NINJA_VERSION_RESULT
)
if(NOT ROUTEPROOF_NINJA_VERSION_RESULT EQUAL 0
   OR ROUTEPROOF_NINJA_VERSION VERSION_LESS 1.11.1)
    message(FATAL_ERROR "RouteProof requires Ninja 1.11.1 or newer")
endif()

set(ROUTEPROOF_EXPECTED_COMPILER_ID "" CACHE STRING
    "Require a compiler ID (GNU or Clang) for the selected build preset")

if(ROUTEPROOF_EXPECTED_COMPILER_ID
   AND NOT "${CMAKE_CXX_COMPILER_ID}" STREQUAL "${ROUTEPROOF_EXPECTED_COMPILER_ID}")
    message(FATAL_ERROR
        "Preset requires ${ROUTEPROOF_EXPECTED_COMPILER_ID}, but CMake selected ${CMAKE_CXX_COMPILER_ID}")
endif()

if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS 12.5.0)
        message(FATAL_ERROR "RouteProof requires GCC 12.5.0 or newer")
    endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "Clang")
    if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS 18.1.8)
        message(FATAL_ERROR "RouteProof requires Clang 18.1.8 or newer")
    endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "AppleClang")
    if(CMAKE_CXX_COMPILER_VERSION VERSION_LESS 21.0.0)
        message(FATAL_ERROR "RouteProof requires Apple Clang 21.0.0 or newer")
    endif()
else()
    message(FATAL_ERROR
        "Supported compilers are GCC 12.5.0+, Clang 18.1.8+, and Apple Clang 21.0.0+")
endif()

add_library(routeproof_core STATIC
    src/input/document.cpp
    src/input/scenario_loader.cpp
    src/model/topology.cpp
    src/spf/shortest_paths.cpp
    src/forwarding/table.cpp
    src/output/baseline.cpp
    src/engine/replay.cpp
    src/analysis/reachability.cpp
    src/output/simulation.cpp
)

target_compile_features(routeproof_core PUBLIC cxx_std_20)
set_target_properties(routeproof_core PROPERTIES
    CXX_EXTENSIONS OFF
)
target_include_directories(routeproof_core PUBLIC include)
target_link_libraries(routeproof_core PRIVATE
    yaml-cpp::yaml-cpp
    nlohmann_json::nlohmann_json
    picosha2
)

add_executable(routeproof app/main.cpp)
set_target_properties(routeproof PROPERTIES CXX_EXTENSIONS OFF)
target_link_libraries(routeproof PRIVATE routeproof_core)
target_compile_definitions(routeproof PRIVATE
    ROUTEPROOF_VERSION="${PROJECT_VERSION}"
)

include(CTest)
if(BUILD_TESTING)
    find_package(Python3 3.9 REQUIRED COMPONENTS Interpreter)
    add_executable(routeproof_topology_check tests/integration/physical_topology.cpp)
    set_target_properties(routeproof_topology_check PROPERTIES CXX_EXTENSIONS OFF)
    target_link_libraries(routeproof_topology_check PRIVATE routeproof_core)
    add_test(NAME input.physical_topology
        COMMAND routeproof_topology_check
                "${CMAKE_CURRENT_SOURCE_DIR}/examples/input/valid/physical-state.yaml")
    add_test(NAME input.input_fixtures
        COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/input/validate_fixtures.py"
                "$<TARGET_FILE:routeproof>")
    add_executable(routeproof_input_limits_check tests/integration/input_limits.cpp)
    set_target_properties(routeproof_input_limits_check PROPERTIES CXX_EXTENSIONS OFF)
    target_link_libraries(routeproof_input_limits_check PRIVATE routeproof_core)
    add_test(NAME input.input_limits
        COMMAND routeproof_input_limits_check
                "${CMAKE_CURRENT_SOURCE_DIR}/examples/input/valid/diamond.yaml")
    add_test(NAME input.input_regressions
        COMMAND "${Python3_EXECUTABLE}"
                "${CMAKE_CURRENT_SOURCE_DIR}/tools/input/validate_regressions.py"
                "$<TARGET_FILE:routeproof>")
    set_tests_properties(input.input_regressions PROPERTIES TIMEOUT 60)
    add_executable(routeproof_routing_check tests/integration/routing.cpp)
    set_target_properties(routeproof_routing_check PROPERTIES CXX_EXTENSIONS OFF)
    target_link_libraries(routeproof_routing_check PRIVATE routeproof_core)
    add_test(NAME routing.routing_contract COMMAND routeproof_routing_check
        "${CMAKE_CURRENT_SOURCE_DIR}/examples/routing/merged-ecmp.json")
    add_test(NAME routing.independent_oracle COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/reference/check_routing.py" "$<TARGET_FILE:routeproof>")
    set_tests_properties(routing.routing_contract routing.independent_oracle PROPERTIES TIMEOUT 60)
    add_executable(routeproof_replay_check tests/integration/replay_analysis.cpp)
    set_target_properties(routeproof_replay_check PROPERTIES CXX_EXTENSIONS OFF)
    target_link_libraries(routeproof_replay_check PRIVATE routeproof_core)
    add_test(NAME replay.replay_checker COMMAND routeproof_replay_check
        "${CMAKE_CURRENT_SOURCE_DIR}/examples/diamond-failures.yaml")
    add_test(NAME replay.independent_replay COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/reference/check_replay.py" "$<TARGET_FILE:routeproof>")
    set_tests_properties(replay.replay_checker replay.independent_replay PROPERTIES TIMEOUT 60)
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang|AppleClang")
    foreach(target routeproof_core routeproof)
        target_compile_options(${target} PRIVATE -Wall -Wextra -Wpedantic)
    endforeach()
    if(BUILD_TESTING)
        target_compile_options(routeproof_topology_check PRIVATE -Wall -Wextra -Wpedantic)
        target_compile_options(routeproof_replay_check PRIVATE -Wall -Wextra -Wpedantic)
        target_compile_options(routeproof_routing_check PRIVATE -Wall -Wextra -Wpedantic)
        target_compile_options(routeproof_input_limits_check PRIVATE -Wall -Wextra -Wpedantic)
    endif()
endif()

message(STATUS "RouteProof model: ospf_spf_v1")
message(STATUS "RouteProof scenario schema: 1")
message(STATUS "RouteProof result schema: 1")
message(STATUS "RouteProof dependencies: yaml-cpp 0.9.0, nlohmann/json 3.12.0, PicoSHA2 1.0.1")
