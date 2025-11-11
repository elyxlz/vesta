# Installation

## Prerequisites

- Node.js (>= 18.0.0 recommended)
- npm (comes with Node.js)

## Using npm (Recommended)

To use the server in your project or MCP host environment, install it as a dependency:

```bash
npm install @sylphlab/pdf-reader-mcp
```

## Running Standalone (for testing/development)

1.  **Clone the repository:**

    ```bash
    git clone https://github.com/sylphlab/pdf-reader-mcp.git
    cd pdf-reader-mcp
    ```

2.  **Install dependencies:**

    ```bash
    npm install
    ```

3.  **Build the project:**

    ```bash
    npm run build
    ```

4.  **Run the server:**
    The server communicates via stdio. You'll typically run it from an MCP host.
    ```bash
    node build/index.js
    ```
    **Important:** Ensure you run this command from the root directory of the project containing the PDFs you want the server to access.

## Using Docker

A Docker image is available on Docker Hub.

```bash
docker pull sylphlab/pdf-reader-mcp:latest
```

To run the container, you need to mount the project directory containing your PDFs into the container's working directory (`/app`):

```bash
docker run -i --rm -v "/path/to/your/project:/app" sylphlab/pdf-reader-mcp:latest
```

Replace `/path/to/your/project` with the actual absolute path to your project folder.
