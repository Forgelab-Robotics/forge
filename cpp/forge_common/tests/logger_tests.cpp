#include "forge_common/forge_common.hpp"

#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>

namespace {

int failures = 0;

void Check(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAILED: " << message << "\n";
    ++failures;
  }
}

void SetEnv(const char* name, const char* value) {
#if defined(_WIN32)
  _putenv_s(name, value);
#else
  setenv(name, value, 1);
#endif
}

void UnsetEnv(const char* name) {
#if defined(_WIN32)
  _putenv_s(name, "");
#else
  unsetenv(name);
#endif
}

void ClearForgeLogEnv() {
  UnsetEnv("FORGE_LOG_LEVEL");
  UnsetEnv("FORGE_LOG_FILE");
  UnsetEnv("FORGE_LOG_CONSOLE");
  UnsetEnv("FORGE_LOG_STREAM");
}

std::string ReadFile(const std::string& path) {
  std::ifstream input(path);
  std::ostringstream contents;
  contents << input.rdbuf();
  return contents.str();
}

}  // namespace

int main() {
  using namespace forge_common;

  ClearForgeLogEnv();
  auto defaults = LoggingConfigFromEnv();
  Check(defaults.level == LogLevel::Info, "default log level is info");
  Check(defaults.enable_console, "console logging enabled by default");
  Check(defaults.stream == "stdout", "default log stream is stdout");
  Check(defaults.log_file.empty(), "default log file is empty");

  SetEnv("FORGE_LOG_LEVEL", "debug");
  SetEnv("FORGE_LOG_FILE", "forge_common_env_test.log");
  SetEnv("FORGE_LOG_CONSOLE", "false");
  SetEnv("FORGE_LOG_STREAM", "stderr");
  auto env_config = LoggingConfigFromEnv();
  Check(env_config.level == LogLevel::Debug, "env log level parsed");
  Check(!env_config.enable_console, "env console flag parsed");
  Check(env_config.stream == "stderr", "env stream parsed");
  Check(env_config.log_file == "forge_common_env_test.log", "env log file parsed");
  ClearForgeLogEnv();

  std::ostringstream stdout_capture;
  auto* old_stdout = std::cout.rdbuf(stdout_capture.rdbuf());
  SetupLogging(LoggingConfig{LogLevel::Warning, true, "stdout", ""});
  auto logger = GetLogger("test");
  logger.Info("hidden");
  logger.Error("shown");
  std::cout.rdbuf(old_stdout);
  auto captured = stdout_capture.str();
  Check(captured.find("hidden") == std::string::npos, "level filter hides info");
  Check(captured.find("shown") != std::string::npos, "level filter keeps error");
  Check(captured.find("test") != std::string::npos, "logger name is included");

  const std::string log_path = "forge_common_file_test.log";
  std::remove(log_path.c_str());
  SetupLogging(LoggingConfig{LogLevel::Debug, false, "stdout", log_path});
  GetLogger("file").Debug("file-message");
  SetupLogging(LoggingConfig{});
  auto file_contents = ReadFile(log_path);
  Check(file_contents.find("file-message") != std::string::npos, "file output works");
  std::remove(log_path.c_str());

  std::ostringstream init_capture;
  old_stdout = std::cout.rdbuf(init_capture.rdbuf());
  ClearForgeLogEnv();
  InitLogging("node-a");
  InitLogging("node-b");
  std::cout.rdbuf(old_stdout);
  auto init_output = init_capture.str();
  Check(init_output.find("node-a") != std::string::npos, "InitLogging logs first node");
  Check(init_output.find("node-b") == std::string::npos, "InitLogging only initializes once");

  if (failures != 0) {
    std::cerr << failures << " failure(s)\n";
    return 1;
  }
  return 0;
}
