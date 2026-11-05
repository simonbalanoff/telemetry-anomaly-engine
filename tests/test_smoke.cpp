#include <gtest/gtest.h>

#include "tae/version.hpp"

TEST(Smoke, VersionIsNotEmpty) {
  EXPECT_FALSE(tae::version().empty());
}
