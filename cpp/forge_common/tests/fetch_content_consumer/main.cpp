#include <forge_common/forge_common.hpp>

int main() {
  forge_common::SetupLogging(forge_common::LoggingConfig{
      forge_common::LogLevel::Info,
      false,
      "stdout",
      "",
  });
  auto logger = forge_common::GetLogger("consumer");
  logger.Info("hello from consumer");
  return 0;
}
