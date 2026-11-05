include(GoogleTest)

add_executable(tae_tests
  test_smoke.cpp
  test_telemetry_header.cpp
)

target_link_libraries(tae_tests PRIVATE
  tae
  tae_options
  GTest::gtest_main
)

gtest_discover_tests(tae_tests)
