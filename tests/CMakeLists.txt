include(GoogleTest)

find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(TAE_GOLDEN_FIXTURE
  "${CMAKE_CURRENT_BINARY_DIR}/fixtures/python_golden.bin"
)

add_custom_command(
  OUTPUT "${TAE_GOLDEN_FIXTURE}"
  COMMAND "${Python3_EXECUTABLE}"
    "${PROJECT_SOURCE_DIR}/python/generate_fixture.py"
    "${TAE_GOLDEN_FIXTURE}"
  DEPENDS
    "${PROJECT_SOURCE_DIR}/python/generate_fixture.py"
    "${PROJECT_SOURCE_DIR}/python/write_binary.py"
  VERBATIM
)

add_custom_target(tae_python_fixture
  DEPENDS "${TAE_GOLDEN_FIXTURE}"
)

add_executable(tae_tests
  test_smoke.cpp
  test_telemetry_header.cpp
  test_telemetry_frame.cpp
  test_telemetry_reader.cpp
  test_python_integration.cpp
)

add_dependencies(tae_tests tae_python_fixture)

target_compile_definitions(tae_tests PRIVATE
  TAE_FIXTURE_PATH="${TAE_GOLDEN_FIXTURE}"
)

target_link_libraries(tae_tests PRIVATE
  tae
  tae_options
  GTest::gtest_main
)

gtest_discover_tests(tae_tests)
