cmake_minimum_required(VERSION 3.24)
project(telemetry_anomaly_engine VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Debug)
endif()

option(TAE_WARNINGS_AS_ERRORS "Treat warnings as errors" ON)
set(TAE_SANITIZER "none" CACHE STRING "Sanitizer to enable: none, asan (address+undefined), tsan (thread)")
set_property(CACHE TAE_SANITIZER PROPERTY STRINGS none asan tsan)

# One interface target carries all our compile flags. Link it to our own
# targets only, so third-party code (googletest) is not held to our warnings.
add_library(tae_options INTERFACE)
if(MSVC)
  target_compile_options(tae_options INTERFACE /W4 /permissive-)
  if(TAE_WARNINGS_AS_ERRORS)
    target_compile_options(tae_options INTERFACE /WX)
  endif()
else()
  target_compile_options(tae_options INTERFACE
    -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion)
  if(TAE_WARNINGS_AS_ERRORS)
    target_compile_options(tae_options INTERFACE -Werror)
  endif()
  if(TAE_SANITIZER STREQUAL "asan")
    target_compile_options(tae_options INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(tae_options INTERFACE -fsanitize=address,undefined)
  elseif(TAE_SANITIZER STREQUAL "tsan")
    target_compile_options(tae_options INTERFACE -fsanitize=thread -fno-omit-frame-pointer)
    target_link_options(tae_options INTERFACE -fsanitize=thread)
  endif()
endif()

# Core library. Add .cpp files to this list as you create them.

add_library(tae
  src/version.cpp
  src/io/telemetry_header.cpp
)

target_include_directories(tae PUBLIC include)
target_compile_features(tae PUBLIC cxx_std_20)
target_link_libraries(tae PRIVATE tae_options)

add_subdirectory(apps/cli)

include(CTest)
if(BUILD_TESTING)
  include(FetchContent)
  FetchContent_Declare(googletest
    URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz)
  set(INSTALL_GTEST OFF CACHE BOOL "" FORCE)
  FetchContent_MakeAvailable(googletest)
  add_subdirectory(tests)
endif()
