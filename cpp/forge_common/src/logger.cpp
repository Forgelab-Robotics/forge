#include "forge_common/forge_common.hpp"

#include <algorithm>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <mutex>
#include <sstream>
#include <utility>

namespace forge_common {
namespace {

std::mutex g_logging_mutex;
LoggingConfig g_config;
std::unique_ptr<std::ofstream> g_file_stream;
std::once_flag g_init_once;

std::string Upper(std::string value) {
  std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
    return static_cast<char>(std::toupper(c));
  });
  return value;
}

bool ParseBool(const char* value, bool default_value) {
  if (value == nullptr) {
    return default_value;
  }
  auto upper = Upper(value);
  return upper == "TRUE" || upper == "1" || upper == "YES" || upper == "ON";
}

std::string EnvString(const char* name) {
  const char* value = std::getenv(name);
  return value == nullptr ? std::string() : std::string(value);
}

bool ShouldLog(LogLevel message_level, LogLevel configured_level) {
  if (configured_level == LogLevel::Off || message_level == LogLevel::Off) {
    return false;
  }
  return static_cast<int>(message_level) >= static_cast<int>(configured_level);
}

std::string Timestamp() {
  auto now = std::chrono::system_clock::now();
  auto time = std::chrono::system_clock::to_time_t(now);
  std::tm tm{};
#if defined(_WIN32)
  localtime_s(&tm, &time);
#else
  localtime_r(&time, &tm);
#endif
  std::ostringstream out;
  out << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
  return out.str();
}

std::ostream& ConsoleStream(const LoggingConfig& config) {
  return config.stream == "stderr" ? std::cerr : std::cout;
}

}  // namespace

LogLevel ParseLogLevel(const std::string& value) {
  auto upper = Upper(value);
  if (upper == "DEBUG") return LogLevel::Debug;
  if (upper == "INFO") return LogLevel::Info;
  if (upper == "WARNING" || upper == "WARN") return LogLevel::Warning;
  if (upper == "ERROR") return LogLevel::Error;
  if (upper == "CRITICAL" || upper == "FATAL") return LogLevel::Critical;
  if (upper == "OFF") return LogLevel::Off;
  return LogLevel::Info;
}

std::string ToString(LogLevel level) {
  switch (level) {
    case LogLevel::Debug:
      return "DEBUG";
    case LogLevel::Info:
      return "INFO";
    case LogLevel::Warning:
      return "WARNING";
    case LogLevel::Error:
      return "ERROR";
    case LogLevel::Critical:
      return "CRITICAL";
    case LogLevel::Off:
      return "OFF";
  }
  return "INFO";
}

LoggingConfig LoggingConfigFromEnv() {
  LoggingConfig config;

  auto level = EnvString("FORGE_LOG_LEVEL");
  if (!level.empty()) {
    config.level = ParseLogLevel(level);
  }

  config.log_file = EnvString("FORGE_LOG_FILE");
  config.enable_console = ParseBool(std::getenv("FORGE_LOG_CONSOLE"), true);

  auto stream = Upper(EnvString("FORGE_LOG_STREAM"));
  config.stream = stream == "STDERR" ? "stderr" : "stdout";

  return config;
}

void SetupLogging(const LoggingConfig& config) {
  std::lock_guard<std::mutex> lock(g_logging_mutex);
  g_config = config;
  if (g_config.stream != "stderr") {
    g_config.stream = "stdout";
  }

  g_file_stream.reset();
  if (!g_config.log_file.empty()) {
    g_file_stream = std::make_unique<std::ofstream>(g_config.log_file, std::ios::app);
    if (!g_file_stream->is_open()) {
      g_file_stream.reset();
      std::cerr << "failed to open forge log file: " << g_config.log_file << "\n";
    }
  }
}

void ConfigureFromEnv() { SetupLogging(LoggingConfigFromEnv()); }

Logger::Logger(std::string name) : name_(std::move(name)) {
  if (name_.empty()) {
    name_ = "forge_common";
  }
}

void Logger::Debug(const std::string& message) const { Log(LogLevel::Debug, message); }

void Logger::Info(const std::string& message) const { Log(LogLevel::Info, message); }

void Logger::Warning(const std::string& message) const { Log(LogLevel::Warning, message); }

void Logger::Error(const std::string& message) const { Log(LogLevel::Error, message); }

void Logger::Critical(const std::string& message) const { Log(LogLevel::Critical, message); }

void Logger::Log(LogLevel level, const std::string& message) const {
  std::lock_guard<std::mutex> lock(g_logging_mutex);
  if (!ShouldLog(level, g_config.level)) {
    return;
  }

  auto line = Timestamp() + " - " + name_ + " - " + ToString(level) + " - " + message + "\n";

  if (g_config.enable_console) {
    ConsoleStream(g_config) << line;
  }
  if (g_file_stream && g_file_stream->is_open()) {
    *g_file_stream << line;
    g_file_stream->flush();
  }
}

Logger GetLogger(std::string name) { return Logger(std::move(name)); }

void InitLogging(const std::string& node_name) {
  std::call_once(g_init_once, [&node_name]() {
    ConfigureFromEnv();
    GetLogger(node_name).Info("logger initialized");
  });
}

}  // namespace forge_common
