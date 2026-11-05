include(GoogleTest)

# Add one line per test file as you create them.
add_executable(tae_tests
  test_smoke.cpp
)
target_link_libraries(tae_tests PRIVATE tae tae_options GTest::gtest_main)
gtest_discover_tests(tae_tests)
