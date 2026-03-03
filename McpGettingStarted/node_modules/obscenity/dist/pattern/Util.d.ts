import type { Node, ParsedPattern } from './Nodes';
export declare function potentiallyMatchesEmptyString(pattern: ParsedPattern): boolean;
export declare function compilePatternToRegExp(pattern: ParsedPattern): RegExp;
export declare function getRegExpStringForNode(node: Node): string;
