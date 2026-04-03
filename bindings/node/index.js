try {
  module.exports = require("../../build/Release/tree_sitter_q_binding");
} catch {
  module.exports = require("../../build/Debug/tree_sitter_q_binding");
}
