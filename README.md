# bobskater

An AST based Python obfuscator that robustly mangles names in Python code

### Current limitations:
* DOES NOT SUPPORT: Annotations, evals, templated strings
* No configuration but instead takes a cautious approach in determining what identifiers to mangle. Globals, kwargs, class namespace identifiers, and others are not obfuscated but this should be user selected in the future
* It is only tested with Python v3.5 and might not work with other AST versions
* Scoping for comprehensions are kind of hacky (and basically follows Python 2 comprehension scope leaking methodology)
* Doesn't support imports of the form import xxx.yyy, as this ast pattern isn't put into the scope and will bomb out

### Installation

```
pip install bobskater
```

### Usage

```
from bobskater import obfuscateFile, obfuscateString

#Takes a file path and overwrites it with the obfuscated file
obfuscateFile(filePath)

#Takes a string of Python code and obfuscates it, returning the result
output = obfuscateString(open('myfile.py', 'r').read())
```

### Developing

See CONTRIBUTING.MD