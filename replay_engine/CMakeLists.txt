cmake_minimum_required(VERSION 3.16)
project(dota2_replay_engine LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_library(dota2replay STATIC src/engine.cpp)
target_include_directories(dota2replay PUBLIC include)
target_compile_options(dota2replay PRIVATE -Wall -Wextra -Wpedantic)

add_executable(dota2-replay-engine src/main.cpp)
target_link_libraries(dota2-replay-engine PRIVATE dota2replay)

enable_testing()
add_executable(test-engine tests/test_engine.cpp)
target_link_libraries(test-engine PRIVATE dota2replay)
add_test(NAME replay-engine-core COMMAND test-engine)
