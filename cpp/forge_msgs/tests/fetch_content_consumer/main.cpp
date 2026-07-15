#include <forge_msgs/forge_msgs.hpp>

#include <iostream>

int main() {
  forge_msgs::Text text{"hello from consumer"};
  auto batch = text.ToRecordBatch();
  if (!batch.ok()) {
    std::cerr << batch.status().ToString() << "\n";
    return 1;
  }

  auto decoded = forge_msgs::Text::FromRecordBatch(**batch);
  if (!decoded.ok()) {
    std::cerr << decoded.status().ToString() << "\n";
    return 1;
  }

  return decoded->text == text.text ? 0 : 1;
}
