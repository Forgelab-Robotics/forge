#pragma once

#include <string>

namespace forge_common {

enum class LogLevel {
  Debug,
  Info,
  Warning,
  Error,
  Critical,
  Off,
};

struct LoggingConfig {
  LogLevel level = LogLevel::Info;
  bool enable_console = true;
  std::string stream = "stdout";
  std::string log_file;
};

LogLevel ParseLogLevel(const std::string& value);
std::string ToString(LogLevel level);

LoggingConfig LoggingConfigFromEnv();
void SetupLogging(const LoggingConfig& config);
void ConfigureFromEnv();

class Logger {
 public:
  explicit Logger(std::string name);

  void Debug(const std::string& message) const;
  void Info(const std::string& message) const;
  void Warning(const std::string& message) const;
  void Error(const std::string& message) const;
  void Critical(const std::string& message) const;

 private:
  void Log(LogLevel level, const std::string& message) const;

  std::string name_;
};

Logger GetLogger(std::string name);
void InitLogging(const std::string& node_name);

}  // namespace forge_common
