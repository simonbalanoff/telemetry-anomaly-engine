#include <iostream>

#include "tae/version.hpp"

int main() {
  std::cout << "telemetry-anomaly-engine " << tae::version() << '\n';
  return 0;
}
