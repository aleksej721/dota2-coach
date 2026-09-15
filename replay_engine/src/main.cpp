#include "dota2replay/engine.hpp"

#include <chrono>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
    if (argc != 3 || std::string(argv[1]) != "scan") {
        std::cerr << "usage: dota2-replay-engine scan <replay.dem>\n";
        return 2;
    }
    try {
        const auto started = std::chrono::steady_clock::now();
        const auto report = dota2replay::scan_replay(argv[2]);
        const auto elapsed = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - started).count();
        std::cout << dota2replay::report_json(report) << '\n';
        std::cerr << "decoded in " << elapsed << " s\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "replay rejected: " << error.what() << '\n';
        return 1;
    }
}
