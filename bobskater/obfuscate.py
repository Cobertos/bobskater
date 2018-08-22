"""
Obfuscate a python file so it still works

Has issues:
Doesn't support any sort of annotations (skips them, should be okay for now?)
Hacky patch of comprehensions (see top, reverses for one specific thing so the _fields prints out the right way due to)
Comprehesions do not push a stack and basically use Python 2 behavior where their identifiers leak
Eval, strings, and other oddities are unconsidered for identifiers. Attributes are unconsidered too
"""
import keyword
import sys
import ast
import string
import unicodedata
import itertools
import logging
from collections import defaultdict, namedtuple
import astunparse

from .frameUtils import Frame, FrameEntry, getIdsFromNode, setIdsOnNode


def iter_fields_patch(node):
    """
    patch of ast.py iter_fields so that ast.ListComp, ast.SetComp, etc are iterated in reverse so that
    the for clause comes before the expression evaluated by the for clause (we might be able to take
    this out now that theirs the 2 stage approach but unconfirmed)
    """
    it = node._fields if not isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)) else \
        reversed(node._fields)
    for field in it:
        try:
            yield field, getattr(node, field)
        except AttributeError:
            pass
ast.iter_fields = iter_fields_patch

def validIdentifierIterator(version=2):
    """
    Compute strings of the valid identifier characters (for Python2, including start
    and "tail" characters after the first one)
    """
    #Determine characters we can use
    if version == 2:
        validIDStart = string.ascii_letters + "_"
        validID = string.ascii_letters + "_" + string.digits
    else:
        #Version 3
        #Get all unicode categories
        unicode_category = defaultdict(str)
        for c in map(chr, range(min(sys.maxunicode + 1,20000))): #sys.maxunicode is SLOW
            unicode_category[unicodedata.category(c)] += c

        #id_start = Lu, Ll, Lt, Lm, Lo, Nl, the underscore, and characters with the Other_ID_Start property>
        validIDStart = (unicode_category["Lu"] + unicode_category["Ll"] +
            unicode_category["Lt"] + unicode_category["Lm"] + unicode_category["Lo"] + 
            unicode_category["Nl"] + "_")
        #id_continue = id_start, plus Mn, Mc, Nd, Pc and others with the Other_ID_Continue property>
        validID = (validIDStart + unicode_category["Mn"] + unicode_category["Mc"] + 
            unicode_category["Nd"] + unicode_category["Pc"])

    #Yield the strings, starting with 1 character strings
    for c in validIDStart:
        if c in keyword.kwlist:
            continue #Skip keywords
        yield c

    #Yield 2+ character strings
    tailLength = 1
    while True:
        for c in validIDStart:
            for c2 in itertools.combinations_with_replacement(validID, tailLength):
                c2 = "".join(c2)
                if c + c2 in keyword.kwlist:
                    continue #Skip keywords
                yield c + c2

        tailLength += 1

class FrameTrackingNodeVisitor(ast.NodeVisitor):
    """
    A NodeTransformer that builds a graph of all relevant identifiers, and their
    relevant scoepes
    Do not inherit from this but instead instantiate it. It cannot give an accurate
    picture for a given identifier if scope usages occur out of order between definition
    and usage
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger = logging.getLogger(self.__class__.__name__)

        #The root frame tracking identifiers and the current frame
        #that we're at in the ast walking process
        self._rootFrame = Frame.getBuiltinFrame()
        self._currentFrame = self._rootFrame

    def _handleEnterNode(self, node):
        """
        Takes a new node and appends, modifies, or pops the identifiers in that
        node to the appropriate stack frame
        """
        #Amazingly helpful and even necessary reference/reading to edit
        #this section would be:
        #
        #http://greentreesnakes.readthedocs.io/en/latest/nodes.html#
        #
        #as it demonstrates how the ast changes through Python versions
        #and which identifiers come up as node.Name and which come up as
        #a raw string on a field (Ctrl+F raw)

        #SCOPE DEFINING CASES (nodes that have an identifier that will make it add
        #to the current scope)
        #Handle global/nonlocal (Python3) statement
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            frame = self._rootFrame.children[0] #For global statement, always use the same stack frame
            #global_stmt ::=  "global" identifier ("," identifier)*
            for strId in node.names:
                if isinstance(node, ast.Nonlocal):
                    #Find scope for nonlocal argument, if None then TODO
                    frame = self._currentFrame.getScopedEntry(strId)
                    if frame is None:
                        raise NotImplementedError("TODO: No scope for nonlocal declaration, what do?")

                #If in the current scope is already defined (the assigned and then used the statement)
                #do what python does and warn but leave it as local
                #This is Python 3.5 behavior so this might need to be changed if ever a problem
                if self._currentFrame.getScopedEntry(strId) != frame:
                    self._logger.warning("Global/nonlocal found when variable already in local scope")
                else:
                    self._logger.debug("[+Entry]: " + str(node.__class__.__name__) + " \"" + strId + "\"")
                    frame.addEntry(FrameEntry(id=strId, source=node))
        #TODO: Annotations (for everything x:)
        #Handle Name (which handles anything that doesn't use raw strings)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                self._logger.debug("[+Entry]: " + str(node.__class__.__name__) + " \"" + node.id + "\"")
                self._currentFrame.addEntry(
                    FrameEntry(id=node.id, source=node, ctx=node.ctx))
            #Store
            #Or Param (Python 2 ast.arg Name node ctx, instead of raw string)
            elif isinstance(node.ctx, (ast.Store,ast.Param)):
                self._logger.debug("[+Entry]: " + str(node.__class__.__name__) + " \"" + node.id + "\"")
                self._currentFrame.addEntry(
                    FrameEntry(id=node.id, source=node, ctx=ast.Store()))
            #Delete
            #ignore these, consider Python will throw an error and they don't modify scope
        #For everything else that has an ID, rely on getIdsFromNode to get the
        #names and handle normally
        else:
            ids = getIdsFromNode(node)
            for strId in ids:
                self._logger.debug("[+Entry]: " + str(node.__class__.__name__) + " \"" + strId + "\"")
                self._currentFrame.addEntry(
                    FrameEntry(id=strId, source=node))

        if Frame.nodeCreatesFrame(node):
            frame = Frame(source=node)
            self._currentFrame.addFrame(frame)
            self._currentFrame = frame

            self._logger.debug("[+Frame]: " + str(node.__class__.__name__) + " \"" +
                    (node.name if hasattr(node, "name") else "") + "\"")

    def _handleLeaveNode(self, node):
        """
        Takes a node we're leaving and, if necessary, performs cleanup
        related to moving it off of the stack
        """
        if Frame.nodeCreatesFrame(node):
            self._logger.debug("[-Frame]")
            self._currentFrame = self._currentFrame.parent

    def generic_visit(self, node):
        self._handleEnterNode(node)
        super().generic_visit(node)
        self._handleLeaveNode(node)

    def getRootFrame(self):
        return self._rootFrame

class ObfuscationTransformer(ast.NodeTransformer):
    """
    Parses out things that obfuscate our code, 
    NOTE: Comments won't be in the AST anyway, so no worries
    """
    def __init__(self, rootFrame, *args, **kwargs):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._rootFrame = rootFrame
        self._nodeStack = []
        self._debugMsg = None

        #TODO: Name should eventually be unique per scope, as we
        #can better obfuscate by using the same names in scopes that
        #don't touch each other
        self._name = validIdentifierIterator()
        super().__init__(*args, **kwargs)

    def getMangledName(self, nodeStack, strId):
        """
        Determine whether a strId used somewhere should be
        mangled
        """
        frameEntry = self._rootFrame.findEntryAtStack(nodeStack, strId)
        isBuiltin = frameEntry.parent == self._rootFrame

        alreadyMangledName = frameEntry.value
        if alreadyMangledName:
            self._debugMsg = "Already mangled; \"" + alreadyMangledName + "\""
            return alreadyMangledName #It has a mangled name, use it
        if alreadyMangledName == False:
            self._debugMsg = "Already mangled; Don't mangle"
            return False #It was instructed to not mangle

        if isBuiltin:
            #Dont rename builtins
            self._debugMsg = "Don't mangle; Builtin"
            frameEntry.value = False
            return False

        stackNode = frameEntry.parent.source #ClassDef, FunctionDef, etc that defined the stack
        sourceNode = frameEntry.source #The node that the id came from
        if isinstance(stackNode, (ast.ClassDef,ast.Module)):
            #Anything in the class namespace (static variables, methods)
            #and anything in the module namespace (will probs be exported)
            #should not be mangled
            self._debugMsg = "Don't mangle; Class or Module namespace"
            frameEntry.value = False
            return False
        elif isinstance(sourceNode, ast.alias):
            #An imported name, don't mangle those
            self._debugMsg = "Don't mangle; import name"
            frameEntry.value = False
            return False
        elif isinstance(sourceNode, ast.arg) and hasattr(nodeStack[-1], "defaults") and nodeStack[-1].defaults:
            self._debugMsg = "Don't mangle; kwargs"
            #An argument node with keyword args, don't mangle the keyword args
            #Slice the keyword arguments
            #TODO: I have no idea if this functions in not Python 3.5
            argumentsNode = nodeStack[-1]
            #Slice the number of default nodes from the end
            kwStrs = list(map(lambda n: n.arg, argumentsNode.args[-len(argumentsNode.defaults):]))
            self._logger.debug("kwarg debug %s %s %s", kwStrs, strId, strId in kwStrs)
            if strId in kwStrs:
                frameEntry.value = False
                return False

        #Otherwise, return the name we're mangling to for this
        #string ID and store it
        #Make sure the mangleName isn't in the current scope already (as an unmangled name)
        ids = frameEntry.parent.getAllIds()
        mangledName = next(self._name)
        while mangledName in ids:
            mangledName = next(self._name)
        frameEntry.value = mangledName
        return mangledName

    def generic_visit(self, node):
        #Remove docstrings
        if (isinstance(node, ast.Expr) and 
            isinstance(self._nodeStack[-1], 
                (ast.FunctionDef,ast.ClassDef,ast.Module)) and 
            isinstance(node.value, ast.Str)):
            return ast.Pass()

        #Mangle names
        ids = getIdsFromNode(node)
        if self._logger.isEnabledFor(logging.DEBUG):
            oldIds = ids[:]
        for idx, strId in enumerate(ids):
            mangleTo = self.getMangledName(self._nodeStack, strId)
            if not mangleTo:
                continue
            ids[idx] = mangleTo
        setIdsOnNode(node, ids)
        if ids and self._logger.isEnabledFor(logging.DEBUG):
            self._logger.debug(node.__class__.__name__ + 
                ": " + (str(oldIds) if oldIds else None) + 
                " => " + (str(ids) if ids else None) + " [" +
                self._debugMsg + "]")
            self._debugMsg = ""

        #Go in to deeper nodes
        self._nodeStack.append(node)
        super().generic_visit(node)
        self._nodeStack.pop()
        
        return node

def obfuscateString(s):
    #Parse string for AST
    sAst = ast.parse(s)
    #Walk the AST once total to get all the scope information
    ftnv = FrameTrackingNodeVisitor()
    ftnv.visit(sAst)
    logging.getLogger(__name__).debug(ftnv.getRootFrame())
    #Walk the AST a second time to obfuscate identifiers with
    #queriable scope info
    sAst = ObfuscationTransformer(ftnv.getRootFrame()).visit(sAst)
    #Unparse AST into source code
    return astunparse.unparse(sAst)

def obfuscateFile(fp):
    f = open(fp, "r")
    s = f.read()
    f.close()
    s = obfuscateString(s)
    f = open(fp, "w")
    f.write(s)
    f.close()
