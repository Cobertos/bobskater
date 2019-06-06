# Internal Documentation

This library is broken up into two parts:

1. The `FrameTrackingNodeVisitor` extends `ast.NodeVisitor`. By passing it the AST for a file, it will process the entire thing and return scoping information for all identifiers found. These are processed as `FrameTrackingNodeVisitor.Frame` and `FrameTrackingNodeVisitor.FrameEntry` and the root `FrameTrackingNodeVisitor.Frame` is returned with public methods to query scoping information

2. The `ReleaseObfuscationTransformer`. This transforms the given AST into the obfuscated AST. It will internally use `FrameTrackingNodeVisitor` to get the scoping information for a file to determine how to obfuscate it.
