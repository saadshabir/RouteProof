#include "routeproof/input/scenario_loader.hpp"
#include "routeproof/version.hpp"
#include "routeproof/output/baseline.hpp"
#include <chrono>
#include "routeproof/output/simulation.hpp"
#include "routeproof/bench/measurement.hpp"
#include <filesystem>
#include <cerrno>
#include <fcntl.h>
#include <unistd.h>

#include <iostream>
#include <string>
#include <string_view>
#include <system_error>

namespace {

void write_artifact(const std::filesystem::path& path, const std::string& content) {
    // O_EXCL rejects every existing directory entry, including dangling
    // symlinks, and closes the race between an existence check and creation.
    const int descriptor = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0666);
    if (descriptor < 0) {
        if (errno == EEXIST) {
            throw std::runtime_error("output artifact already exists; use a fresh output directory");
        }
        throw std::system_error(errno, std::generic_category(), "output artifact create failed");
    }
    try {
        const auto write_all = [&](const std::string_view bytes) {
            std::size_t offset = 0;
            while (offset < bytes.size()) {
                const auto count = ::write(descriptor, bytes.data() + offset, bytes.size() - offset);
                if (count < 0 && errno == EINTR) { continue; }
                if (count <= 0) {
                    throw std::system_error(count < 0 ? errno : EIO, std::generic_category(),
                                            "output artifact write failed");
                }
                offset += static_cast<std::size_t>(count);
            }
        };
        write_all(content);
        write_all("\n");
    } catch (...) {
        ::close(descriptor);
        throw;
    }
    if (::close(descriptor) != 0) {
        throw std::system_error(errno, std::generic_category(), "output artifact close failed");
    }
}

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
           << "Usage: routeproof --help | --version | validate <scenario.yaml> [--normalized] | routes <scenario.yaml> [--timing] | simulate FILE --out DIR | explain RESULT --assertion ID\n\n"
           << "Commands:\n"
           << "  validate FILE              Validate and summarize a scenario\n"
           << "  validate FILE --normalized Print canonical normalized scenario JSON\n"
           << "  routes FILE [--timing]      Print baseline routes; optional timing JSON on stderr\n"
           << "  simulate FILE --out DIR    Replay events and check all ECMP branches\n"
           << "  explain RESULT --assertion ID  Explain recorded failures\n";
    output << "  bench --profile FILE --out DIR  Collect frozen workload time/RSS evidence\n"
           << "  bench-sample FILE --out DIR     Instrument one scenario (harness worker)\n";
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

    if (std::string_view{argv[1]} == "bench") {
        try { return routeproof::bench::run_harness(argc, argv); }
        catch (const std::exception& error) {
            std::cerr << "routeproof: benchmark incomplete: " << escape_output(error.what()) << '\n'; return 3;
        }
    }
    if (std::string_view{argv[1]} == "simulate" || std::string_view{argv[1]} == "explain" ||
        std::string_view{argv[1]} == "bench-sample") {
        const bool instrument = std::string_view{argv[1]} == "bench-sample";
        const bool simulate = std::string_view{argv[1]} != "explain";
        if (argc != 5 || std::string_view{argv[3]} != (simulate ? "--out" : "--assertion")) {
            print_help(std::cerr); return 2;
        }
        try {
            if (!simulate) {
                const auto explanation = routeproof::output::explain(argv[2], argv[4]);
                std::cout << explanation.json;
                return explanation.exit_code;
            }
            const auto loaded = routeproof::input::load_scenario(argv[2]);
            const auto loaded_rss = instrument ? routeproof::bench::steady_rss_bytes() : 0;
            routeproof::output::SimulationMetrics metrics;
            const auto start = std::chrono::steady_clock::now();
            const auto result = routeproof::output::simulate(loaded, {}, instrument ? &metrics : nullptr);
            const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now() - start).count();
            const std::filesystem::path directory(argv[4]);
            std::filesystem::create_directories(directory);
            auto write = [&](const char* name, const std::string& content) {
                write_artifact(directory / name, content);
            };
            const auto occupied = [&](const char* name) {
                return std::filesystem::symlink_status(directory / name).type() != std::filesystem::file_type::not_found;
            };
            if (occupied("result.json") || occupied("run.json") || (instrument && occupied("sample.json"))) {
                throw std::runtime_error("output artifacts already exist; use a fresh output directory");
            }
            write("run.json", routeproof::output::run_manifest(loaded, result, argv[2], elapsed));
            write("result.json", result.json);
            if (instrument) { write("sample.json", routeproof::bench::sample_manifest(loaded, result, metrics, loaded_rss, elapsed)); }
            std::cout << "result: " << escape_output((directory / "result.json").string()) << '\n';
            return result.exit_code;
        } catch (const routeproof::input::InputError& error) {
            std::cerr << "routeproof: " << escape_output(error.what()) << '\n'; return 2;
        } catch (const std::exception& error) {
            std::cerr << "routeproof: operation incomplete: " << escape_output(error.what()) << '\n'; return 3;
        }
    }

    if (std::string_view{argv[1]} == "routes") {
        if ((argc != 3 && argc != 4) ||
            (argc == 4 && std::string_view{argv[3]} != "--timing")) {
            print_help(std::cerr);
            return 2;
        }
        try {
            const auto loaded = routeproof::input::load_scenario(argv[2]);
            const auto state = routeproof::spf::initial_state(loaded.topology);
            const auto start = std::chrono::steady_clock::now();
            const auto tables = routeproof::forwarding::compute(loaded.topology, state);
            const auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::steady_clock::now() - start).count();
            std::cout << routeproof::output::baseline_json(loaded, state, tables) << '\n';
            if (argc == 4) {
                std::cerr << "{\"baseline_compute_ns\":" << elapsed << "}\n";
            }
            return 0;
        } catch (const routeproof::input::InputError& error) {
            std::cerr << "routeproof: " << escape_output(error.what()) << '\n';
            return 2;
        } catch (const std::exception& error) {
            std::cerr << "routeproof: baseline calculation incomplete: " << escape_output(error.what()) << '\n';
            return 3;
        }
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

    std::cerr << "routeproof: command not implemented: " << escape_output(argv[1])
              << "\n";
    return 3;
}
