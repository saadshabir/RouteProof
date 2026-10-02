#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/version.hpp"

#include <iostream>
#include <string>
#include <string_view>

namespace {

std::string escape_output(const std::string_view text) {
    constexpr char hex[] = "0123456789abcdef";
    std::string escaped;
    for (std::size_t index = 0U; index < text.size(); ++index) {
        const auto byte = static_cast<unsigned char>(text[index]);
        if (byte == '\\') {
            escaped += "\\\\";
        } else if (byte == '\n') {
            escaped += "\\n";
        } else if (byte == '\r') {
            escaped += "\\r";
        } else if (byte == '\t') {
            escaped += "\\t";
        } else if (byte < 0x20U || byte == 0x7fU) {
            escaped += "\\x";
            escaped += hex[byte >> 4U];
            escaped += hex[byte & 0x0fU];
        } else if (byte >= 0x80U) {
            const std::size_t width = byte >= 0xc2U && byte <= 0xdfU   ? 2U
                                      : byte >= 0xe0U && byte <= 0xefU ? 3U
                                      : byte >= 0xf0U && byte <= 0xf4U ? 4U
                                                                       : 0U;
            bool valid = width != 0U && width <= text.size() - index;
            for (std::size_t offset = 1U; valid && offset < width; ++offset) {
                const auto continuation = static_cast<unsigned char>(text[index + offset]);
                valid = continuation >= 0x80U && continuation <= 0xbfU;
            }
            if (valid) {
                const auto second = static_cast<unsigned char>(text[index + 1U]);
                valid = !((byte == 0xe0U && second < 0xa0U) || (byte == 0xedU && second > 0x9fU) ||
                          (byte == 0xf0U && second < 0x90U) || (byte == 0xf4U && second > 0x8fU));
            }
            if (!valid) {
                escaped += "\\x";
                escaped += hex[byte >> 4U];
                escaped += hex[byte & 0x0fU];
            } else if (byte == 0xc2U && static_cast<unsigned char>(text[index + 1U]) <= 0x9fU) {
                const auto control = static_cast<unsigned char>(text[++index]);
                escaped += "\\u00";
                escaped += hex[control >> 4U];
                escaped += hex[control & 0x0fU];
            } else {
                escaped.append(text.substr(index, width));
                index += width - 1U;
            }
        } else {
            escaped += text[index];
        }
    }
    return escaped;
}

void print_help(std::ostream& output) {
    output << "RouteProof " << routeproof::version << "\n"
           << "Usage: routeproof --help | --version | validate <scenario.yaml> [--normalized]\n\n"
           << "Commands:\n"
           << "  validate FILE              Validate and summarize a scenario\n"
           << "  validate FILE --normalized Print canonical normalized scenario JSON\n";
}

void print_version(std::ostream& output) {
    output << "RouteProof " << routeproof::version << "\n"
           << "model: " << routeproof::model_id << "\n"
           << "scenario schema: " << routeproof::scenario_schema_version << "\n"
           << "result schema: " << routeproof::result_schema_version << "\n";
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc == 2 && std::string_view{argv[1]} == "--version") {
        print_version(std::cout);
        return 0;
    }

    if (argc == 2 && std::string_view{argv[1]} == "--help") {
        print_help(std::cout);
        return 0;
    }

    if (argc == 1) {
        print_help(std::cerr);
        return 2;
    }

    if (std::string_view{argv[1]} == "validate") {
        if ((argc != 3 && argc != 4) ||
            (argc == 4 && std::string_view{argv[3]} != "--normalized")) {
            print_help(std::cerr);
            return 2;
        }
        try {
            const routeproof::input::LoadedScenario loaded =
                routeproof::input::load_scenario(argv[2]);
            if (argc == 4) {
                std::cout << loaded.normalized_json << '\n';
                return 0;
            }
            std::cout << "valid\n"
                      << "name: " << escape_output(loaded.topology.scenario.name) << '\n'
                      << "model: " << routeproof::model_id << '\n'
                      << "schema_version: " << routeproof::scenario_schema_version << '\n'
                      << "routers: " << loaded.topology.scenario.routers.size() << '\n'
                      << "links: " << loaded.topology.scenario.links.size() << '\n'
                      << "prefixes: " << loaded.topology.scenario.prefixes.size() << '\n'
                      << "events: " << loaded.topology.scenario.events.size() << '\n'
                      << "assertions: " << loaded.topology.scenario.assertions.size() << '\n'
                      << "scenario_sha256: " << loaded.scenario_sha256 << '\n';
            return 0;
        } catch (const routeproof::input::InputError& error) {
            std::cerr << "routeproof: " << escape_output(error.what()) << '\n';
            return 2;
        } catch (const std::exception& error) {
            std::cerr << "routeproof: validation failed: " << escape_output(error.what()) << '\n';
            return 2;
        }
    }

    std::cerr << "routeproof: command not implemented in Phase 1: " << escape_output(argv[1])
              << "\n";
    return 3;
}
