#!/usr/bin/env python3
"""
Test runner script for YGO API backend tests.

Provides convenient commands to run different test suites with proper
configuration and reporting.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def get_project_root():
    """Get the project root directory."""
    current_dir = Path(__file__).parent
    # Go up until we find the project root (contains ygoapi directory)
    while current_dir.parent != current_dir:
        if (current_dir / "ygoapi").exists():
            return current_dir
        current_dir = current_dir.parent
    return Path(__file__).parent.parent


def run_command(command, description="Running command"):
    """Run a shell command and return the result."""
    print(f"\n{'='*60}")
    print(f"{description}")
    print(f"Command: {' '.join(command)}")
    print(f"{'='*60}")

    start_time = time.time()

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)

        duration = time.time() - start_time

        if result.stdout:
            print("STDOUT:")
            print(result.stdout)

        if result.stderr:
            print("STDERR:")
            print(result.stderr)

        print(f"Duration: {duration:.2f}s")
        print(f"Exit Code: {result.returncode}")

        return result.returncode == 0, result, duration
    except Exception as e:
        print(f"Error running command: {e}")
        return False, None, 0


def generate_test_report(test_results):
    """Generate a comprehensive test report in JSON format."""
    project_root = get_project_root()
    report_dir = project_root / "tests" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now().isoformat(),
        "project": "YGO API Backend",
        "environment": {
            "python_version": sys.version,
            "platform": sys.platform,
            "cwd": str(project_root),
        },
        "summary": {
            "total_checks": len(test_results),
            "passed": sum(1 for result in test_results.values() if result.get("success", False)),
            "failed": sum(
                1 for result in test_results.values() if not result.get("success", False)
            ),
            "overall_success": all(
                result.get("success", False) for result in test_results.values()
            ),
        },
        "results": test_results,
    }

    # Write JSON report
    json_report_path = report_dir / f"test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Write latest report (for CI/CD)
    latest_report_path = report_dir / "latest_test_report.json"
    with open(latest_report_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n📊 Test report generated: {json_report_path}")
    print(f"📊 Latest report: {latest_report_path}")

    return report


def run_unit_tests(verbose=False, coverage=False):
    """Run unit tests."""
    project_root = get_project_root()
    os.chdir(project_root)

    command = ["python", "-m", "pytest", "tests/unit/"]

    if verbose:
        command.append("-v")

    if coverage:
        command.extend(
            [
                "--cov=ygoapi",
                "--cov-report=html:tests/coverage/html",
                "--cov-report=term-missing",
                "--cov-report=xml:tests/coverage/coverage.xml",
                "--cov-report=json:tests/coverage/coverage.json",
            ]
        )

    # Add JUnit XML output for CI/CD
    command.extend(["--junit-xml=tests/reports/unit_tests.xml"])

    success, result, duration = run_command(command, "Running Unit Tests")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
    }


def run_integration_tests(verbose=False):
    """Run integration tests."""
    project_root = get_project_root()
    os.chdir(project_root)

    command = ["python", "-m", "pytest", "tests/integration/"]

    if verbose:
        command.append("-v")

    # Add JUnit XML output for CI/CD
    command.extend(["--junit-xml=tests/reports/integration_tests.xml"])

    success, result, duration = run_command(command, "Running Integration Tests")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
    }


def run_all_tests(verbose=False, coverage=False):
    """Run all tests."""
    project_root = get_project_root()
    os.chdir(project_root)

    command = ["python", "-m", "pytest", "tests/"]

    if verbose:
        command.append("-v")

    if coverage:
        command.extend(
            [
                "--cov=ygoapi",
                "--cov-report=html:tests/coverage/html",
                "--cov-report=term-missing",
                "--cov-report=xml:tests/coverage/coverage.xml",
                "--cov-report=json:tests/coverage/coverage.json",
            ]
        )

    # Add JUnit XML output for CI/CD
    command.extend(["--junit-xml=tests/reports/all_tests.xml"])

    success, result, duration = run_command(command, "Running All Tests")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
    }


def run_specific_test(test_path, verbose=False):
    """Run a specific test file or test function."""
    project_root = get_project_root()
    os.chdir(project_root)

    command = ["python", "-m", "pytest", test_path]

    if verbose:
        command.append("-v")

    # Add JUnit XML output for CI/CD
    command.extend(["--junit-xml=tests/reports/specific_test.xml"])

    success, result, duration = run_command(command, f"Running Specific Test: {test_path}")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
        "test_path": test_path,
    }


def run_linting():
    """Run code linting with flake8."""
    project_root = get_project_root()
    os.chdir(project_root)

    # Check if flake8 is available
    try:
        subprocess.run(["flake8", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("flake8 not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "flake8"])

    command = [
        "flake8",
        "ygoapi/",
        "tests/",
        "--max-line-length=100",
        "--exclude=__pycache__,*.pyc,.git,venv,env",
        "--ignore=E203,W503",  # Black compatibility
        "--output-file=tests/reports/flake8_report.txt",
        "--tee",  # Also print to stdout
    ]

    success, result, duration = run_command(command, "Running Code Linting")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
    }


def run_type_checking():
    """Run type checking with mypy."""
    project_root = get_project_root()
    os.chdir(project_root)

    # Check if mypy is available
    try:
        subprocess.run(["mypy", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("mypy not found. Installing...")
        subprocess.run([sys.executable, "-m", "pip", "install", "mypy"])

    command = [
        "mypy",
        "ygoapi/",
        "--ignore-missing-imports",
        "--no-strict-optional",
        "--txt-report",
        "tests/reports/mypy",
        "--html-report",
        "tests/reports/mypy_html",
    ]

    success, result, duration = run_command(command, "Running Type Checking")

    return {
        "success": success,
        "duration": duration,
        "output": result.stdout if result else "",
        "errors": result.stderr if result else "",
        "exit_code": result.returncode if result else 1,
    }


def generate_coverage_report():
    """Generate detailed coverage report."""
    project_root = get_project_root()
    os.chdir(project_root)

    # Run tests with coverage
    result = run_all_tests(coverage=True)

    if result["success"]:
        print(f"\n{'='*60}")
        print("Coverage Report Generated")
        print(f"{'='*60}")
        print(f"HTML Report: {project_root}/tests/coverage/html/index.html")
        print(f"XML Report: {project_root}/tests/coverage/coverage.xml")
        print(f"JSON Report: {project_root}/tests/coverage/coverage.json")

        # Try to open HTML report if on macOS
        if sys.platform == "darwin":
            try:
                subprocess.run(["open", str(project_root / "tests/coverage/html/index.html")])
            except:
                pass

    return result


def run_quick_check():
    """Run a quick validation check (linting + basic tests)."""
    print("Running Quick Validation Check...")

    results = {}

    # Run linting
    results["linting"] = run_linting()

    # Run unit tests only (faster than full suite)
    results["unit_tests"] = run_unit_tests(verbose=True)

    # Generate report
    report = generate_test_report(results)

    # Summary
    print(f"\n{'='*60}")
    print("QUICK CHECK SUMMARY")
    print(f"{'='*60}")
    print(f"Linting: {'✓ PASSED' if results['linting']['success'] else '✗ FAILED'}")
    print(f"Unit Tests: {'✓ PASSED' if results['unit_tests']['success'] else '✗ FAILED'}")

    overall_success = report["summary"]["overall_success"]
    print(f"Overall: {'✓ PASSED' if overall_success else '✗ FAILED'}")

    return overall_success


def run_full_validation():
    """Run complete validation suite."""
    print("Running Full Validation Suite...")

    results = {}

    # Run linting
    results["linting"] = run_linting()

    # Run type checking
    results["type_checking"] = run_type_checking()

    # Run all tests with coverage
    results["all_tests"] = run_all_tests(verbose=True, coverage=True)

    # Generate comprehensive report
    report = generate_test_report(results)

    # Summary
    print(f"\n{'='*60}")
    print("FULL VALIDATION SUMMARY")
    print(f"{'='*60}")
    for check_name, result in results.items():
        status = "✓ PASSED" if result["success"] else "✗ FAILED"
        print(f"{check_name.replace('_', ' ').title()}: {status}")

    overall_success = report["summary"]["overall_success"]
    print(f"Overall: {'✓ PASSED' if overall_success else '✗ FAILED'}")

    if overall_success:
        print(f"\n🎉 All checks passed! Code is ready for deployment.")
    else:
        print(f"\n❌ Some checks failed. Please review and fix issues.")

        # Print failure details for CI/CD
        print(f"\n📋 FAILURE DETAILS:")
        for check_name, result in results.items():
            if not result["success"]:
                print(f"\n{check_name.upper()} FAILED:")
                if result.get("errors"):
                    print(result["errors"])

    return overall_success


def setup_test_environment():
    """Set up the test environment."""
    project_root = get_project_root()
    os.chdir(project_root)

    print("Setting up test environment...")

    # Create necessary directories
    directories = ["tests/coverage", "tests/reports", "tests/coverage/html"]

    for directory in directories:
        dir_path = project_root / directory
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"Created directory: {dir_path}")

    # Install test dependencies
    print("Installing test dependencies...")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "pytest",
            "pytest-cov",
            "pytest-asyncio",
            "pytest-html",
            "flake8",
            "mypy",
        ]
    )

    print("✓ Test environment setup complete!")
    return True


def clean_test_artifacts():
    """Clean test artifacts and cache files."""
    project_root = get_project_root()

    patterns_to_clean = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "tests/coverage",
        "tests/reports",
        ".pytest_cache",
        ".coverage",
        "*.egg-info",
        "htmlcov",
    ]

    print("Cleaning test artifacts...")

    for pattern in patterns_to_clean:
        for path in project_root.glob(pattern):
            if path.is_file():
                path.unlink()
                print(f"Removed file: {path}")
            elif path.is_dir():
                import shutil

                shutil.rmtree(path)
                print(f"Removed directory: {path}")

    print("✓ Test artifacts cleaned!")


def main():
    """Main entry point for the test runner."""
    parser = argparse.ArgumentParser(
        description="YGO API Backend Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_tests.py --unit                    # Run unit tests only
  python run_tests.py --integration             # Run integration tests only
  python run_tests.py --all --coverage          # Run all tests with coverage
  python run_tests.py --quick                   # Quick validation check
  python run_tests.py --full                    # Full validation suite
  python run_tests.py --specific tests/unit/test_models.py  # Run specific test
  python run_tests.py --lint                    # Run linting only
  python run_tests.py --setup                   # Setup test environment
        """,
    )

    # Test execution options
    parser.add_argument("--unit", action="store_true", help="Run unit tests")
    parser.add_argument("--integration", action="store_true", help="Run integration tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument(
        "--specific", metavar="TEST_PATH", help="Run specific test file or function"
    )

    # Validation options
    parser.add_argument(
        "--quick", action="store_true", help="Run quick validation (lint + unit tests)"
    )
    parser.add_argument("--full", action="store_true", help="Run full validation suite")

    # Individual check options
    parser.add_argument("--lint", action="store_true", help="Run code linting")
    parser.add_argument("--type-check", action="store_true", help="Run type checking")
    parser.add_argument("--coverage", action="store_true", help="Generate coverage report")

    # Utility options
    parser.add_argument("--setup", action="store_true", help="Setup test environment")
    parser.add_argument("--clean", action="store_true", help="Clean test artifacts")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # If no arguments provided, show help
    if len(sys.argv) == 1:
        parser.print_help()
        return

    success = True

    try:
        if args.setup:
            success = setup_test_environment()

        elif args.clean:
            clean_test_artifacts()

        elif args.quick:
            success = run_quick_check()

        elif args.full:
            success = run_full_validation()

        elif args.unit:
            result = run_unit_tests(args.verbose, args.coverage)
            success = result["success"]

        elif args.integration:
            result = run_integration_tests(args.verbose)
            success = result["success"]

        elif args.all:
            result = run_all_tests(args.verbose, args.coverage)
            success = result["success"]

        elif args.specific:
            result = run_specific_test(args.specific, args.verbose)
            success = result["success"]

        elif args.lint:
            result = run_linting()
            success = result["success"]

        elif args.type_check:
            result = run_type_checking()
            success = result["success"]

        elif args.coverage:
            result = generate_coverage_report()
            success = result["success"]

        else:
            parser.print_help()
            return

    except KeyboardInterrupt:
        print("\n\nTest execution interrupted by user.")
        sys.exit(130)
    except Exception as e:
        print(f"\nError during test execution: {e}")
        sys.exit(1)

    # Exit with appropriate code for CI/CD
    exit_code = 0 if success else 1
    print(f"\n🔚 Test runner exiting with code: {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
