#include <exception>
#include <iostream>
#include <string>

#include "commands.hpp"
#include "tae/version.hpp"

int main(int argc, char **argv) {
    try {
        if (argc == 1) {
            std::cout << "telemetry-anomaly-engine " << tae::version() << '\n';
            return 0;
        }
        const std::string command = argv[1];
        if (command == "verify" && argc == 3) {
            tae::cli::verify(argv[2]);
        } else if (command == "score" && argc == 9 &&
                   std::string(argv[8]) == "--synthetic-fixture") {
            tae::cli::score(argv[2], argv[3], argv[4], argv[5], argv[6], argv[7],
                            tae::io::HeaderPolicy::SyntheticFixture);
        } else if (command == "score" && argc == 8) {
            tae::cli::score(argv[2], argv[3], argv[4], argv[5], argv[6], argv[7]);
        } else {
            std::cerr << "Usage:\n"
                      << "  tae verify TELEMETRY\n"
                      << "  tae score TELEMETRY TRAIN_MASK SCORES METADATA WINDOW ALPHA\n";
            return 1;
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "tae: " << error.what() << '\n';
        return 1;
    }
}
