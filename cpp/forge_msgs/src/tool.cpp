#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <locale>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <string>
#include <vector>

#include "detail.hpp"

namespace forge_msgs {

using namespace detail;

namespace {

constexpr std::int64_t kMaxSafeJsonInteger = 9007199254740991LL;
constexpr std::size_t kMaxJsonNesting = 64;
constexpr const char* kToolEndpointProtocol = "forge.tool.endpoint/v1alpha1";

class StrictJsonObjectValidator {
 public:
  explicit StrictJsonObjectValidator(const std::string& value)
      : value_(value) {}

  bool Validate() {
    SkipWhitespace();
    if (AtEnd() || value_[position_] != '{') {
      return Fail("root must be an object");
    }
    if (!ParseObject(0)) {
      return false;
    }
    SkipWhitespace();
    if (!AtEnd()) {
      return Fail("trailing data is not allowed");
    }
    return true;
  }

  const std::string& error() const { return error_; }

 private:
  bool AtEnd() const { return position_ == value_.size(); }

  bool Fail(const std::string& message) {
    if (error_.empty()) {
      error_ = message + " at byte " + std::to_string(position_);
    }
    return false;
  }

  void SkipWhitespace() {
    while (!AtEnd()) {
      const char character = value_[position_];
      if (character != ' ' && character != '\t' && character != '\r' &&
          character != '\n') {
        break;
      }
      ++position_;
    }
  }

  bool ParseValue(std::size_t depth) {
    if (depth > kMaxJsonNesting) {
      return Fail("JSON nesting exceeds 64");
    }

    SkipWhitespace();
    if (AtEnd()) {
      return Fail("expected a JSON value");
    }

    switch (value_[position_]) {
      case '{':
        return ParseObject(depth);
      case '[':
        return ParseArray(depth);
      case '"':
        return ParseString(nullptr);
      case 't':
        return ParseLiteral("true");
      case 'f':
        return ParseLiteral("false");
      case 'n':
        return ParseLiteral("null");
      default:
        if (value_[position_] == '-' ||
            (value_[position_] >= '0' && value_[position_] <= '9')) {
          return ParseNumber();
        }
        return Fail("expected a JSON value");
    }
  }

  bool ParseObject(std::size_t depth) {
    if (depth > kMaxJsonNesting) {
      return Fail("JSON nesting exceeds 64");
    }

    ++position_;
    SkipWhitespace();
    if (!AtEnd() && value_[position_] == '}') {
      ++position_;
      return true;
    }

    std::set<std::string> keys;
    while (true) {
      SkipWhitespace();
      if (AtEnd() || value_[position_] != '"') {
        return Fail("object keys must be strings");
      }

      std::string key;
      if (!ParseString(&key)) {
        return false;
      }
      if (!keys.insert(key).second) {
        return Fail("duplicate object key");
      }

      SkipWhitespace();
      if (AtEnd() || value_[position_] != ':') {
        return Fail("expected ':' after object key");
      }
      ++position_;
      if (!ParseValue(depth + 1)) {
        return false;
      }

      SkipWhitespace();
      if (AtEnd()) {
        return Fail("unterminated object");
      }
      if (value_[position_] == '}') {
        ++position_;
        return true;
      }
      if (value_[position_] != ',') {
        return Fail("expected ',' or '}' in object");
      }
      ++position_;
    }
  }

  bool ParseArray(std::size_t depth) {
    ++position_;
    SkipWhitespace();
    if (!AtEnd() && value_[position_] == ']') {
      ++position_;
      return true;
    }

    while (true) {
      if (!ParseValue(depth + 1)) {
        return false;
      }
      SkipWhitespace();
      if (AtEnd()) {
        return Fail("unterminated array");
      }
      if (value_[position_] == ']') {
        ++position_;
        return true;
      }
      if (value_[position_] != ',') {
        return Fail("expected ',' or ']' in array");
      }
      ++position_;
    }
  }

  bool ParseString(std::string* decoded) {
    ++position_;
    while (!AtEnd()) {
      const unsigned char character =
          static_cast<unsigned char>(value_[position_]);
      if (character == '"') {
        ++position_;
        return true;
      }
      if (character == '\\') {
        ++position_;
        if (!ParseEscape(decoded)) {
          return false;
        }
        continue;
      }
      if (character < 0x20) {
        return Fail("unescaped control character in string");
      }
      if (character < 0x80) {
        if (decoded != nullptr) {
          decoded->push_back(static_cast<char>(character));
        }
        ++position_;
        continue;
      }

      std::uint32_t code_point = 0;
      if (!ParseUtf8CodePoint(&code_point)) {
        return false;
      }
      if (decoded != nullptr) {
        AppendUtf8(code_point, decoded);
      }
    }
    return Fail("unterminated string");
  }

  bool ParseEscape(std::string* decoded) {
    if (AtEnd()) {
      return Fail("unterminated string escape");
    }

    const char escape = value_[position_++];
    switch (escape) {
      case '"':
      case '\\':
      case '/':
        if (decoded != nullptr) {
          decoded->push_back(escape);
        }
        return true;
      case 'b':
        if (decoded != nullptr) decoded->push_back('\b');
        return true;
      case 'f':
        if (decoded != nullptr) decoded->push_back('\f');
        return true;
      case 'n':
        if (decoded != nullptr) decoded->push_back('\n');
        return true;
      case 'r':
        if (decoded != nullptr) decoded->push_back('\r');
        return true;
      case 't':
        if (decoded != nullptr) decoded->push_back('\t');
        return true;
      case 'u':
        break;
      default:
        return Fail("invalid string escape");
    }

    std::uint32_t code_point = 0;
    if (!ParseHexQuad(&code_point)) {
      return false;
    }
    if (code_point >= 0xD800 && code_point <= 0xDBFF) {
      if (position_ + 2 > value_.size() || value_[position_] != '\\' ||
          value_[position_ + 1] != 'u') {
        return Fail("high surrogate must be followed by a low surrogate");
      }
      position_ += 2;
      std::uint32_t low_surrogate = 0;
      if (!ParseHexQuad(&low_surrogate)) {
        return false;
      }
      if (low_surrogate < 0xDC00 || low_surrogate > 0xDFFF) {
        return Fail("high surrogate must be followed by a low surrogate");
      }
      code_point =
          0x10000 + ((code_point - 0xD800) << 10) + (low_surrogate - 0xDC00);
    } else if (code_point >= 0xDC00 && code_point <= 0xDFFF) {
      return Fail("unpaired low surrogate");
    }

    if (decoded != nullptr) {
      AppendUtf8(code_point, decoded);
    }
    return true;
  }

  bool ParseHexQuad(std::uint32_t* value) {
    if (position_ + 4 > value_.size()) {
      return Fail("incomplete Unicode escape");
    }

    std::uint32_t result = 0;
    for (std::size_t index = 0; index < 4; ++index) {
      const char character = value_[position_++];
      result <<= 4;
      if (character >= '0' && character <= '9') {
        result += static_cast<std::uint32_t>(character - '0');
      } else if (character >= 'a' && character <= 'f') {
        result += static_cast<std::uint32_t>(character - 'a' + 10);
      } else if (character >= 'A' && character <= 'F') {
        result += static_cast<std::uint32_t>(character - 'A' + 10);
      } else {
        return Fail("invalid Unicode escape");
      }
    }
    *value = result;
    return true;
  }

  bool ParseUtf8CodePoint(std::uint32_t* value) {
    const unsigned char lead = static_cast<unsigned char>(value_[position_]);
    std::size_t length = 0;
    std::uint32_t code_point = 0;
    std::uint32_t minimum = 0;
    if (lead >= 0xC2 && lead <= 0xDF) {
      length = 2;
      code_point = lead & 0x1F;
      minimum = 0x80;
    } else if (lead >= 0xE0 && lead <= 0xEF) {
      length = 3;
      code_point = lead & 0x0F;
      minimum = 0x800;
    } else if (lead >= 0xF0 && lead <= 0xF4) {
      length = 4;
      code_point = lead & 0x07;
      minimum = 0x10000;
    } else {
      return Fail("invalid UTF-8 in string");
    }

    if (position_ + length > value_.size()) {
      return Fail("incomplete UTF-8 sequence in string");
    }
    for (std::size_t index = 1; index < length; ++index) {
      const unsigned char continuation =
          static_cast<unsigned char>(value_[position_ + index]);
      if ((continuation & 0xC0) != 0x80) {
        return Fail("invalid UTF-8 continuation byte in string");
      }
      code_point = (code_point << 6) | (continuation & 0x3F);
    }
    if (code_point < minimum || code_point > 0x10FFFF ||
        (code_point >= 0xD800 && code_point <= 0xDFFF)) {
      return Fail("invalid Unicode scalar value in string");
    }

    position_ += length;
    *value = code_point;
    return true;
  }

  static void AppendUtf8(std::uint32_t code_point, std::string* output) {
    if (code_point <= 0x7F) {
      output->push_back(static_cast<char>(code_point));
    } else if (code_point <= 0x7FF) {
      output->push_back(static_cast<char>(0xC0 | (code_point >> 6)));
      output->push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    } else if (code_point <= 0xFFFF) {
      output->push_back(static_cast<char>(0xE0 | (code_point >> 12)));
      output->push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3F)));
      output->push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    } else {
      output->push_back(static_cast<char>(0xF0 | (code_point >> 18)));
      output->push_back(static_cast<char>(0x80 | ((code_point >> 12) & 0x3F)));
      output->push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3F)));
      output->push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    }
  }

  bool ParseLiteral(const char* literal) {
    const std::string expected(literal);
    if (value_.compare(position_, expected.size(), expected) != 0) {
      return Fail("invalid JSON literal");
    }
    position_ += expected.size();
    return true;
  }

  bool ParseNumber() {
    const std::size_t start = position_;
    if (value_[position_] == '-') {
      ++position_;
      if (AtEnd()) {
        return Fail("expected digit after '-'");
      }
    }

    if (value_[position_] == '0') {
      ++position_;
      if (!AtEnd() && value_[position_] >= '0' && value_[position_] <= '9') {
        return Fail("leading zero in number");
      }
    } else if (value_[position_] >= '1' && value_[position_] <= '9') {
      do {
        ++position_;
      } while (!AtEnd() && value_[position_] >= '0' &&
               value_[position_] <= '9');
    } else {
      return Fail("expected digit in number");
    }

    bool is_integer = true;
    if (!AtEnd() && value_[position_] == '.') {
      is_integer = false;
      ++position_;
      const std::size_t fraction_start = position_;
      while (!AtEnd() && value_[position_] >= '0' && value_[position_] <= '9') {
        ++position_;
      }
      if (position_ == fraction_start) {
        return Fail("fraction requires at least one digit");
      }
    }

    if (!AtEnd() && (value_[position_] == 'e' || value_[position_] == 'E')) {
      is_integer = false;
      ++position_;
      if (!AtEnd() && (value_[position_] == '+' || value_[position_] == '-')) {
        ++position_;
      }
      const std::size_t exponent_start = position_;
      while (!AtEnd() && value_[position_] >= '0' && value_[position_] <= '9') {
        ++position_;
      }
      if (position_ == exponent_start) {
        return Fail("exponent requires at least one digit");
      }
    }

    if (is_integer) {
      std::uint64_t magnitude = 0;
      std::size_t digit = start + (value_[start] == '-' ? 1 : 0);
      const std::uint64_t maximum =
          static_cast<std::uint64_t>(kMaxSafeJsonInteger);
      for (; digit < position_; ++digit) {
        const std::uint64_t next =
            static_cast<std::uint64_t>(value_[digit] - '0');
        if (magnitude > (maximum - next) / 10) {
          return Fail("integer exceeds interoperable range");
        }
        magnitude = magnitude * 10 + next;
      }
      return true;
    }

    std::istringstream input(value_.substr(start, position_ - start));
    input.imbue(std::locale::classic());
    double parsed = 0.0;
    input >> parsed;
    if (!input.fail()) {
      return std::isfinite(parsed) ||
             Fail("floating-point number is not finite");
    }
    if (SignificandIsZero(start, position_) ||
        DecimalOrderIsNegative(start, position_)) {
      return true;
    }
    return Fail("floating-point number is out of range");
  }

  bool SignificandIsZero(std::size_t start, std::size_t end) const {
    for (std::size_t index = start;
         index < end && value_[index] != 'e' && value_[index] != 'E'; ++index) {
      if (value_[index] >= '1' && value_[index] <= '9') {
        return false;
      }
    }
    return true;
  }

  bool DecimalOrderIsNegative(std::size_t start, std::size_t end) const {
    std::size_t cursor = start + (value_[start] == '-' ? 1 : 0);
    const std::size_t integer_start = cursor;
    while (cursor < end && value_[cursor] >= '0' && value_[cursor] <= '9') {
      ++cursor;
    }
    const std::size_t integer_digits = cursor - integer_start;

    std::size_t digit_index = 0;
    std::size_t first_nonzero = std::string::npos;
    cursor = integer_start;
    while (cursor < end && value_[cursor] != 'e' && value_[cursor] != 'E') {
      if (value_[cursor] != '.') {
        if (first_nonzero == std::string::npos && value_[cursor] != '0') {
          first_nonzero = digit_index;
        }
        ++digit_index;
      }
      ++cursor;
    }

    bool base_negative = false;
    std::uint64_t base_magnitude = 0;
    if (first_nonzero < integer_digits) {
      base_magnitude =
          static_cast<std::uint64_t>(integer_digits - first_nonzero - 1);
    } else {
      base_negative = true;
      base_magnitude =
          static_cast<std::uint64_t>(first_nonzero + 1 - integer_digits);
    }

    if (cursor == end) {
      return base_negative;
    }
    ++cursor;
    bool exponent_negative = false;
    if (value_[cursor] == '+' || value_[cursor] == '-') {
      exponent_negative = value_[cursor] == '-';
      ++cursor;
    }

    std::uint64_t exponent_magnitude = 0;
    bool exponent_overflow = false;
    for (; cursor < end; ++cursor) {
      const std::uint64_t next =
          static_cast<std::uint64_t>(value_[cursor] - '0');
      if (exponent_magnitude >
          (std::numeric_limits<std::uint64_t>::max() - next) / 10) {
        exponent_overflow = true;
        break;
      }
      exponent_magnitude = exponent_magnitude * 10 + next;
    }
    if (exponent_overflow) {
      return exponent_negative;
    }

    if (exponent_negative) {
      return base_negative || exponent_magnitude > base_magnitude;
    }
    return base_negative && exponent_magnitude < base_magnitude;
  }

  const std::string& value_;
  std::size_t position_ = 0;
  std::string error_;
};

arrow::Status ValidateStrictJsonObject(const std::string& name,
                                       const std::string& value) {
  StrictJsonObjectValidator validator(value);
  if (!validator.Validate()) {
    return arrow::Status::Invalid(
        name, " must be a valid strict JSON object: ", validator.error());
  }
  return arrow::Status::OK();
}

std::vector<std::shared_ptr<arrow::Field>> ToolMessageFields() {
  return {arrow::field("protocol", arrow::utf8(), false),
          arrow::field("message_type", arrow::utf8(), false),
          arrow::field("request_id", arrow::utf8(), true),
          arrow::field("invocation_id", arrow::utf8(), true),
          arrow::field("attempt_id", arrow::utf8(), true),
          arrow::field("endpoint_id", arrow::utf8(), false),
          arrow::field("endpoint_instance_id", arrow::utf8(), true),
          arrow::field("operation", arrow::utf8(), true),
          arrow::field("sequence", arrow::int64(), true),
          arrow::field("payload_json", arrow::utf8(), false)};
}

arrow::Status RequireExactToolMessageSchema(const arrow::RecordBatch& batch) {
  const auto expected = arrow::schema(ToolMessageFields());
  if (!batch.schema()->Equals(*expected, false)) {
    return arrow::Status::Invalid(
        "ToolMessage RecordBatch schema must exactly match ",
        expected->ToString(), "; got ", batch.schema()->ToString());
  }
  return arrow::Status::OK();
}

bool DecodeUtf8CodePoint(const std::string& value, std::size_t* position,
                         std::uint32_t* code_point) {
  const auto lead = static_cast<unsigned char>(value[*position]);
  if (lead < 0x80) {
    *code_point = lead;
    ++*position;
    return true;
  }

  std::size_t length = 0;
  std::uint32_t decoded = 0;
  std::uint32_t minimum = 0;
  if (lead >= 0xC2 && lead <= 0xDF) {
    length = 2;
    decoded = lead & 0x1F;
    minimum = 0x80;
  } else if (lead >= 0xE0 && lead <= 0xEF) {
    length = 3;
    decoded = lead & 0x0F;
    minimum = 0x800;
  } else if (lead >= 0xF0 && lead <= 0xF4) {
    length = 4;
    decoded = lead & 0x07;
    minimum = 0x10000;
  } else {
    return false;
  }

  if (*position + length > value.size()) {
    return false;
  }
  for (std::size_t index = 1; index < length; ++index) {
    const auto continuation =
        static_cast<unsigned char>(value[*position + index]);
    if ((continuation & 0xC0) != 0x80) {
      return false;
    }
    decoded = (decoded << 6) | (continuation & 0x3F);
  }
  if (decoded < minimum || decoded > 0x10FFFF ||
      (decoded >= 0xD800 && decoded <= 0xDFFF)) {
    return false;
  }

  *position += length;
  *code_point = decoded;
  return true;
}

bool IsUnicodeWhitespace(std::uint32_t code_point) {
  return (code_point >= 0x09 && code_point <= 0x0D) || code_point == 0x20 ||
         code_point == 0x85 || code_point == 0xA0 || code_point == 0x1680 ||
         (code_point >= 0x2000 && code_point <= 0x200A) ||
         code_point == 0x2028 || code_point == 0x2029 || code_point == 0x202F ||
         code_point == 0x205F || code_point == 0x3000;
}

arrow::Status ValidateNonempty(const std::string& name,
                               const std::string& value) {
  std::size_t position = 0;
  bool has_non_whitespace = false;
  while (position < value.size()) {
    std::uint32_t code_point = 0;
    if (!DecodeUtf8CodePoint(value, &position, &code_point)) {
      return arrow::Status::Invalid(name, " must contain valid UTF-8");
    }
    has_non_whitespace = has_non_whitespace || !IsUnicodeWhitespace(code_point);
  }
  if (!has_non_whitespace) {
    return arrow::Status::Invalid(name, " must be non-empty");
  }
  return arrow::Status::OK();
}

arrow::Status ValidateOptionalNonempty(
    const std::string& name, const std::optional<std::string>& value) {
  if (value) {
    return ValidateNonempty(name, *value);
  }
  return arrow::Status::OK();
}

bool IsSupportedMessageType(const std::string& value) {
  return value == "endpoint.register" || value == "endpoint.unregister" ||
         value == "endpoint.registry.response" ||
         value == "endpoint.status" ||
         value == "tool.invoke.request" || value == "tool.invoke.response" ||
         value == "tool.status.request" || value == "tool.status.response" ||
         value == "tool.result.request" || value == "tool.result.response" ||
         value == "tool.control.request" || value == "tool.control.response" ||
         value == "tool.event" || value == "tool.error";
}

bool IsManagementMessage(const std::string& value) {
  return value == "endpoint.register" || value == "endpoint.unregister" ||
         value == "endpoint.registry.response" || value == "endpoint.status";
}

bool ManagementMessageRequiresRequestId(const std::string& value) {
  return value == "endpoint.register" || value == "endpoint.unregister" ||
         value == "endpoint.registry.response";
}

}  // namespace

arrow::Status ToolMessage::Validate() const {
  if (protocol != kToolEndpointProtocol) {
    return arrow::Status::Invalid("protocol must equal ",
                                  kToolEndpointProtocol);
  }
  if (!IsSupportedMessageType(message_type)) {
    return arrow::Status::Invalid("unsupported message_type: ", message_type);
  }

  ARROW_RETURN_NOT_OK(ValidateOptionalNonempty("request_id", request_id));
  ARROW_RETURN_NOT_OK(ValidateOptionalNonempty("invocation_id", invocation_id));
  ARROW_RETURN_NOT_OK(ValidateOptionalNonempty("attempt_id", attempt_id));
  ARROW_RETURN_NOT_OK(ValidateNonempty("endpoint_id", endpoint_id));
  ARROW_RETURN_NOT_OK(
      ValidateOptionalNonempty("endpoint_instance_id", endpoint_instance_id));
  if (!endpoint_instance_id && IsManagementMessage(message_type)) {
    return arrow::Status::Invalid(
        "endpoint_instance_id must be non-null for endpoint management messages");
  }
  ARROW_RETURN_NOT_OK(ValidateOptionalNonempty("operation", operation));

  if (IsManagementMessage(message_type)) {
    if (ManagementMessageRequiresRequestId(message_type) && !request_id) {
      return arrow::Status::Invalid(
          "request_id must be non-null for endpoint management exchanges");
    }
    if (message_type == "endpoint.status" && request_id) {
      return arrow::Status::Invalid(
          "request_id must be null for unsolicited endpoint.status");
    }
    if (invocation_id || attempt_id || operation || sequence) {
      return arrow::Status::Invalid(
          "endpoint management messages require null "
          "invocation_id, attempt_id, operation, "
          "and sequence");
    }
  } else {
    if (!invocation_id || !attempt_id || !operation) {
      return arrow::Status::Invalid(
          "Tool execution messages require non-null "
          "invocation_id, attempt_id, and operation");
    }
    if (message_type == "tool.event") {
      if (request_id) {
        return arrow::Status::Invalid("request_id must be null for tool.event");
      }
    } else if (!request_id) {
      return arrow::Status::Invalid(
          "request_id must be non-null for non-event Tool execution messages");
    }
  }

  if (message_type == "tool.event") {
    if (!sequence || *sequence < 0 || *sequence > kMaxSafeJsonInteger) {
      return arrow::Status::Invalid("sequence must be in [0, ",
                                    kMaxSafeJsonInteger, "]");
    }
  } else if (sequence) {
    return arrow::Status::Invalid(
        "sequence must be null for non-event messages");
  }

  return ValidateStrictJsonObject("payload_json", payload_json);
}

arrow::Result<std::shared_ptr<arrow::RecordBatch>> ToolMessage::ToRecordBatch()
    const {
  ARROW_RETURN_NOT_OK(Validate());
  ARROW_ASSIGN_OR_RAISE(auto protocol_array, ScalarString(protocol));
  ARROW_ASSIGN_OR_RAISE(auto message_type_array, ScalarString(message_type));
  ARROW_ASSIGN_OR_RAISE(auto request_id_array, OptionalString(request_id));
  ARROW_ASSIGN_OR_RAISE(auto invocation_id_array,
                        OptionalString(invocation_id));
  ARROW_ASSIGN_OR_RAISE(auto attempt_id_array, OptionalString(attempt_id));
  ARROW_ASSIGN_OR_RAISE(auto endpoint_id_array, ScalarString(endpoint_id));
  ARROW_ASSIGN_OR_RAISE(auto endpoint_instance_id_array,
                        OptionalString(endpoint_instance_id));
  ARROW_ASSIGN_OR_RAISE(auto operation_array, OptionalString(operation));
  ARROW_ASSIGN_OR_RAISE(auto sequence_array, OptionalI64(sequence));
  ARROW_ASSIGN_OR_RAISE(auto payload_json_array, ScalarString(payload_json));
  return MakeBatch(ToolMessageFields(),
                   {protocol_array, message_type_array, request_id_array,
                    invocation_id_array, attempt_id_array, endpoint_id_array,
                    endpoint_instance_id_array, operation_array, sequence_array,
                    payload_json_array});
}

arrow::Result<ToolMessage> ToolMessage::FromRecordBatch(
    const arrow::RecordBatch& batch) {
  ARROW_RETURN_NOT_OK(RequireOneRow(batch));
  ARROW_RETURN_NOT_OK(RequireExactToolMessageSchema(batch));
  ToolMessage value;
  ARROW_ASSIGN_OR_RAISE(value.protocol, ReadString(batch, "protocol"));
  ARROW_ASSIGN_OR_RAISE(value.message_type, ReadString(batch, "message_type"));
  ARROW_ASSIGN_OR_RAISE(value.request_id,
                        ReadOptionalString(batch, "request_id"));
  ARROW_ASSIGN_OR_RAISE(value.invocation_id,
                        ReadOptionalString(batch, "invocation_id"));
  ARROW_ASSIGN_OR_RAISE(value.attempt_id,
                        ReadOptionalString(batch, "attempt_id"));
  ARROW_ASSIGN_OR_RAISE(value.endpoint_id, ReadString(batch, "endpoint_id"));
  ARROW_ASSIGN_OR_RAISE(value.endpoint_instance_id,
                        ReadOptionalString(batch, "endpoint_instance_id"));
  ARROW_ASSIGN_OR_RAISE(value.operation,
                        ReadOptionalString(batch, "operation"));
  ARROW_ASSIGN_OR_RAISE(value.sequence, ReadOptionalI64(batch, "sequence"));
  ARROW_ASSIGN_OR_RAISE(value.payload_json, ReadString(batch, "payload_json"));
  ARROW_RETURN_NOT_OK(value.Validate());
  return value;
}

}  // namespace forge_msgs
