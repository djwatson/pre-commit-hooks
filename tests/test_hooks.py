#!/usr/bin/env python3
"""Tests clang-format, clang-tidy, and oclint against .c and .cpp
With this snippet:

    int main() {  int i;  return 10;}

- Triggers clang-format because what should be on 4 lines is on 1
- Triggers clang-tidy because "magical number" 10 is used
- Triggers oclint because short variable name is used

pytest_generate_tests comes from pytest documentation and allows for
table tests to be generated and each treated as a test by pytest.
This allows for 45 tests with a descrition instead of 3 which
functionally tests the same thing.
"""
import os
import re
import shutil
import subprocess as sp

import pytest

import tests.test_utils as utils
from hooks.clang_format import ClangFormatCmd
from hooks.clang_tidy import ClangTidyCmd
from hooks.cppcheck import CppcheckCmd
from hooks.cpplint import CpplintCmd
from hooks.include_what_you_use import IncludeWhatYouUseCmd
from hooks.oclint import OCLintCmd
from hooks.uncrustify import UncrustifyCmd


def get_multifile_scenarios_no_diff(err_files):
    """Create tests to verify that commands are handling both err.c/err.cpp as input correctly and that --no-diff disables diff output."""
    expected_err = b""
    scenarios = [
        [ClangFormatCmd, ["--style=google", "--no-diff"], err_files, expected_err, 1],
        [UncrustifyCmd, ["-c", "tests/uncrustify_defaults.cfg", "--no-diff"], err_files, expected_err, 1],
    ]
    return scenarios


def generate_list_tests():
    """Generate the scenarios for class (45)

    This is all the arg (6) and file (4) combinations
    +2x tests:
        * Call the shell hooks installed with pip to mimic end user use
        * Call via importing the command classes to verify expectations"""
    versions = utils.get_versions()

    pwd = os.getcwd()
    err_c = os.path.join(pwd, "tests/test_repo/err.c")
    err_cpp = os.path.join(pwd, "tests/test_repo/err.cpp")
    ok_c = os.path.join(pwd, "tests/test_repo/ok.c")
    ok_cpp = os.path.join(pwd, "tests/test_repo/ok.cpp")

    ok_str = b""

    clang_format_args_sets = [["--style=google"], ["--style=google", "-i"]]
    clang_format_err = """{0}
====================
--- original

+++ formatted

@@ -1,2 +1,5 @@

 #include {1}
-int main(){{int i;return;}}
+int main() {{
+  int i;
+  return;
+}}
"""  # noqa: E501
    cf_c_err = clang_format_err.format(err_c, "<stdio.h>").encode()
    cf_cpp_err = clang_format_err.format(err_cpp, "<string>").encode()
    clang_format_output = [ok_str, ok_str, cf_c_err, cf_cpp_err]

    ct_base_args = ["-quiet", "-checks=clang-diagnostic-return-type"]
    # Run normal, plus two in-place arguments
    additional_args = [[], ["-fix"], ["--fix-errors"]]
    clang_tidy_args_sets = [ct_base_args + arg for arg in additional_args]
    clang_tidy_err_str = """{0}:2:18: error: non-void function 'main' should return a value [clang-diagnostic-return-type]
int main(){{int i;return;}}
                 ^
1 error generated.
Error while processing {0}.
"""  # noqa: E501
    clang_tidy_str_c = clang_tidy_err_str.format(err_c, "").encode()
    clang_tidy_str_cpp = clang_tidy_err_str.format(err_cpp).encode()
    clang_tidy_output = [ok_str, ok_str, clang_tidy_str_c, clang_tidy_str_cpp]

    # Specify config file as autogenerated one varies between uncrustify versions.
    # v0.66 on ubuntu creates an invalid config; v0.68 on osx does not.
    unc_base_args = ["-c", "tests/uncrustify_defaults.cfg"]
    unc_addtnl_args = [[], ["--replace", "--no-backup"]]
    uncrustify_arg_sets = [unc_base_args + arg for arg in unc_addtnl_args]
    uncrustify_output = [ok_str, ok_str, cf_c_err, cf_cpp_err]

    cppcheck_arg_sets = [[]]
    # cppcheck adds unnecessary error information.
    # See https://stackoverflow.com/questions/6986033
    cppc_ok = b""
    if versions["cppcheck"] <= "1.88":
        cppcheck_err = "[{}:1]: (style) Unused variable: i\n"
    # They've made changes to messaging
    elif versions["cppcheck"] >= "1.89":
        cppcheck_err = """{}:2:16: style: Unused variable: i [unusedVariable]
int main(){{int i;return;}}
               ^
"""
    else:
        print("Problem parsing version for cppcheck", versions["cppcheck"])
        print("Please create an issue on github.com/pocc/pre-commit-hooks")
        cppcheck_err = b""
    cppcheck_err_c = cppcheck_err.format(err_c).encode()
    cppcheck_err_cpp = cppcheck_err.format(err_cpp).encode()
    cppcheck_output = [cppc_ok, cppc_ok, cppcheck_err_c, cppcheck_err_cpp]

    cpplint_arg_sets = [["--verbose=0", "--quiet"]]
    cpplint_err_str = """\
Done processing {0}
Total errors found: 5
{0}:0:  No copyright message found.  You should have a line: "Copyright [year] <Copyright Owner>"  [legal/copyright] [5]
{0}:2:  More than one command on the same line  [whitespace/newline] [0]
{0}:2:  Missing space after ;  [whitespace/semicolon] [3]
{0}:2:  Missing space before {{  [whitespace/braces] [5]
{0}:2:  Could not find a newline character at the end of the file.  [whitespace/ending_newline] [5]
"""
    cpplint_err_c = cpplint_err_str.format(err_c).encode()
    cpplint_err_cpp = cpplint_err_str.format(err_cpp).encode()
    cpplint_output = [cppc_ok, cppc_ok, cpplint_err_c, cpplint_err_cpp]

    iwyu_arg_sets = [[]]
    iwyu_err_c = """{0}:2:18: error: non-void function 'main' should return a value [-Wreturn-type]
int main(){{int i;return;}}
                 ^

{0} should add these lines:

{0} should remove these lines:
- #include <stdio.h>  // lines 1-1

The full include-list for {0}:
---
""".format(
        err_c
    ).encode()
    iwyu_err_cpp = """{0}:2:18: error: non-void function 'main' should return a value [-Wreturn-type]
int main(){{int i;return;}}
                 ^

{0} should add these lines:

{0} should remove these lines:
- #include <string>  // lines 1-1

The full include-list for {0}:
---
""".format(
        err_cpp
    ).encode()
    iwyu_retcodes = [0, 0, 3, 3]
    iwyu_output = [cppc_ok, cppc_ok, iwyu_err_c, iwyu_err_cpp]

    files = [ok_c, ok_cpp, err_c, err_cpp]
    retcodes = [0, 0, 1, 1]
    scenarios = []
    for i in range(len(files)):
        for arg_set in clang_format_args_sets:
            clang_format_scenario = [ClangFormatCmd, arg_set, [files[i]], clang_format_output[i], retcodes[i]]
            scenarios += [clang_format_scenario]
        for arg_set in clang_tidy_args_sets:
            clang_tidy_scenario = [ClangTidyCmd, arg_set, [files[i]], clang_tidy_output[i], retcodes[i]]
            scenarios += [clang_tidy_scenario]
        for arg_set in uncrustify_arg_sets:
            uncrustify_scenario = [UncrustifyCmd, arg_set, [files[i]], uncrustify_output[i], retcodes[i]]
            scenarios += [uncrustify_scenario]
        for arg_set in cppcheck_arg_sets:
            cppcheck_scenario = [CppcheckCmd, arg_set, [files[i]], cppcheck_output[i], retcodes[i]]
            scenarios += [cppcheck_scenario]
        for arg_set in cpplint_arg_sets:
            cpplint_scenario = [CpplintCmd, arg_set, [files[i]], cpplint_output[i], retcodes[i]]
            scenarios += [cpplint_scenario]
        for arg_set in iwyu_arg_sets:
            iwyu_scenario = [IncludeWhatYouUseCmd, arg_set, [files[i]], iwyu_output[i], iwyu_retcodes[i]]
            scenarios += [iwyu_scenario]

    if os.name != "nt":
        oclint_err = """
Compiler Errors:
(please be aware that these errors will prevent OCLint from analyzing this source code)

{0}:2:18: non-void function 'main' should return a value

Clang Static Analyzer Results:

{0}:2:18: non-void function 'main' should return a value


OCLint Report

Summary: TotalFiles=0 FilesWithViolations=0 P1=0 P2=0 P3=0{1}


[OCLint (http://oclint.org) v{2}]
"""
        # -no-analytics required because in some versions of oclint, this causes oclint to hang (0.13.1)
        oclint_arg_sets = [["-enable-global-analysis", "-enable-clang-static-analyzer", "-no-analytics"]]
        ver_output = sp.check_output(["oclint", "--version"]).decode("utf-8")
        oclint_ver = re.search(r"OCLint version ([\d.]+)\.", ver_output).group(1)
        eol_whitespace = " "
        oclint_err_str_c = oclint_err.format(err_c, eol_whitespace, oclint_ver).encode()
        oclint_err_str_cpp = oclint_err.format(err_cpp, eol_whitespace, oclint_ver).encode()
        oclint_output = [ok_str, ok_str, oclint_err_str_c, oclint_err_str_cpp]
        oclint_retcodes = [0, 0, 6, 6]
        for i in range(len(files)):
            for arg_set in oclint_arg_sets:
                oclint_scenario = [OCLintCmd, arg_set, [files[i]], oclint_output[i], oclint_retcodes[i]]
                scenarios += [oclint_scenario]

    scenarios += get_multifile_scenarios_no_diff([err_c, err_cpp])

    return scenarios


class TestHooks:
    """Test all C Linters: clang-format, clang-tidy, and oclint."""

    @classmethod
    def setup_class(cls):
        """Create test files that will be used by other tests."""
        os.makedirs("tests/test_repo/temp", exist_ok=True)
        scenarios = generate_list_tests()
        filenames = ["tests/test_repo/" + f for f in ["ok.c", "ok.cpp", "err.c", "err.cpp"]]
        utils.set_compilation_db(filenames)
        cls.scenarios = []
        for test_type in [cls.run_cmd_class, cls.run_shell_cmd]:
            for s in scenarios:
                type_name = test_type.__name__
                desc = " ".join([type_name, s[0].command, " ".join(s[2]), " ".join(s[1])])
                test_scenario = [
                    desc,
                    {
                        "test_type": test_type,
                        "cmd": s[0],
                        "args": s[1],
                        "files": s[2],
                        "expd_output": s[3],
                        "expd_retcode": s[4],
                    },
                ]
                cls.scenarios += [test_scenario]

    @staticmethod
    def determine_edit_in_place(cmd_name, args):
        """runtime means to check if cmd/args will edit files"""
        clang_format_in_place = cmd_name == "clang-format" and "-i" in args
        clang_tidy_in_place = cmd_name == "clang-tidy" and ("-fix" in args or "--fix-errors" in args)
        uncrustify_in_place = cmd_name == "uncrustify" and "--replace" in args
        return clang_format_in_place or clang_tidy_in_place or uncrustify_in_place

    def test_run(self, test_type, cmd, args, files, expd_output, expd_retcode):
        """Test each command's class from its python file
        and the command for each generated by setup.py."""
        fix_in_place = self.determine_edit_in_place(cmd.command, args)
        has_err_file = any(["err.c" in f for f in files])
        use_temp_files = fix_in_place and has_err_file
        if use_temp_files:
            temp_files = list()
            for f in files:
                temp_file = utils.create_temp_dir_for(f)
                expd_output = expd_output.replace(f.encode(), temp_file.encode())
                temp_files.append(temp_file)
            files = temp_files
            utils.set_compilation_db(files)
        all_args = files + args
        test_type(cmd, all_args, expd_output, expd_retcode)
        if use_temp_files:
            for f in files:
                temp_dir = os.path.dirname(f)
                shutil.rmtree(temp_dir)

    @staticmethod
    def run_cmd_class(cmd_class, all_args, target_output, target_retcode):
        """Test the command class in each python hook file"""
        cmd = cmd_class(all_args)
        if target_retcode == 0:
            cmd.run()
        else:
            with pytest.raises(SystemExit):
                cmd.run()
                # If this continues with no system exit, print info
                print(b"stdout:`" + cmd.stdout + b"`")
                print(b"stderr:`" + cmd.stderr + b"`")
                print("returncode:", cmd.returncode)
        actual = cmd.stdout + cmd.stderr
        retcode = cmd.returncode
        utils.assert_equal(target_output, actual)
        assert target_retcode == retcode

    @staticmethod
    def run_shell_cmd(cmd_class, all_args, target_output, target_retcode):
        """Use command generated by setup.py and installed by pip
        Ex. oclint => oclint-hook for the hook command"""
        cmd_to_run = [cmd_class.command + "-hook", *all_args]
        sp_child = sp.run(cmd_to_run, stdout=sp.PIPE, stderr=sp.PIPE)
        actual = sp_child.stdout + sp_child.stderr
        retcode = sp_child.returncode
        utils.assert_equal(target_output, actual)
        assert target_retcode == retcode

    @staticmethod
    def teardown_class():
        """Delete files generated by these tests."""
        generated_files = ["tests/test_repo/" + f for f in ["ok.plist", "err.plist"]]
        for filename in generated_files:
            if os.path.exists(filename):
                os.remove(filename)
