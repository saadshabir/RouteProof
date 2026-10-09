include(FetchContent)

# Pin reviewed release commits: upstream tags can be moved. Full commit pins
# require a normal clone rather than GIT_SHALLOW (which cannot pin hashes).
FetchContent_Declare(
    yaml-cpp
    GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
    GIT_TAG 56e3bb550c91fd7005566f19c079cb7a503223cf # yaml-cpp-0.9.0
)

FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG 55f93686c01528224f448c19128836e7df245f72 # v3.12.0
)

FetchContent_Declare(
    Catch2
    GIT_REPOSITORY https://github.com/catchorg/Catch2.git
    GIT_TAG 191fa38c9b1596cd2576ab531d4ab4d5e8e05190 # v3.15.2
)

FetchContent_Declare(
    PicoSHA2
    GIT_REPOSITORY https://github.com/okdshin/PicoSHA2.git
    GIT_TAG 161cb3fc4170fa7a3eca9e582cebd27cc4d1fe29 # v1.0.1
)
