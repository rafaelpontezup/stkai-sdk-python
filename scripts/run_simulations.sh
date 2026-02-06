#!/bin/bash
#
# Run rate limiting simulations for stkai-sdk
#
# Usage:
#   ./scripts/run_simulations.sh
#
# This script:
#   1. Sets up the simulation virtual environment (if needed)
#   2. Runs the sweep test across all strategies and contention levels
#   3. Generates graphs in simulations/results/latest/
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print colored message
info() { echo -e "${BLUE}ℹ${NC} $1"; }
success() { echo -e "${GREEN}✓${NC} $1"; }
warning() { echo -e "${YELLOW}⚠${NC} $1"; }
error() { echo -e "${RED}✗${NC} $1"; exit 1; }

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SIMULATIONS_DIR="$PROJECT_ROOT/simulations"

# Check if simulations directory exists
if [ ! -d "$SIMULATIONS_DIR" ]; then
    error "Simulations directory not found: $SIMULATIONS_DIR"
fi

cd "$SIMULATIONS_DIR"

# Setup virtual environment if needed
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    python3 -m venv .venv
    success "Virtual environment created"
fi

# Activate virtual environment
info "Activating virtual environment..."
source .venv/bin/activate

# Install dependencies if needed
if ! python -c "import simpy" 2>/dev/null; then
    info "Installing dependencies..."
    pip install -r requirements.txt
    success "Dependencies installed"
fi

# Run simulations
info "Running simulations..."
echo ""
python run_sweep.py

# Show results location
echo ""
success "Simulations complete!"
info "Results: $SIMULATIONS_DIR/results/latest/"
