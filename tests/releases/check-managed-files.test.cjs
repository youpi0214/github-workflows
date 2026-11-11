const assert = require("node:assert/strict");
const test = require("node:test");
const checkManagedFiles = require("../../scripts/releases/check-managed-files.cjs");

function fixture({
  files = [{ filename: "README.md" }],
  author = "contributor",
  branch = "feature",
  headRepository = 42,
  commitAuthor = author,
  releaseActor = "github-actions[bot]",
} = {}) {
  const pullRequest = {
    number: 1,
    user: { login: author },
    base: { ref: "main" },
    head: { ref: branch, sha: "head", repo: { id: headRepository } },
    changed_files: files.length,
  };

  return {
    releaseActor,
    context: {
      repo: { owner: "owner", repo: "library" },
      payload: {
        repository: { id: 42, default_branch: "main" },
        pull_request: structuredClone(pullRequest),
      },
    },
    core: { info() {} },
    github: {
      rest: {
        pulls: {
          get: async () => ({ data: pullRequest }),
          listFiles: () => {},
        },
        repos: {
          getCommit: async () => ({
            data: { author: { login: commitAuthor } },
          }),
        },
      },
      paginate: async () => files,
    },
  };
}

const managedFiles = [
  { filename: ".release-please-manifest.json" },
  { filename: "version.txt" },
];

const releaseIdentity = {
  author: "github-actions[bot]",
  branch: "release-please--branches--main",
};

test("ordinary changes and manual changelog corrections pass", async () => {
  await checkManagedFiles(fixture({ files: [{ filename: "CHANGELOG.md" }] }));
});

test("human changes to either managed file fail", async () => {
  for (const file of managedFiles) {
    await assert.rejects(
      checkManagedFiles(fixture({ files: [file] })),
      /Release Please/,
    );
  }
});

test("configured Release Please PR passes", async () => {
  await checkManagedFiles(fixture({ files: managedFiles, ...releaseIdentity }));
});

test("copying the release branch name does not authorize a human", async () => {
  await assert.rejects(
    checkManagedFiles(
      fixture({
        files: managedFiles,
        branch: releaseIdentity.branch,
      }),
    ),
    /Release Please/,
  );
});

test("bot author alone and fork PRs do not bypass the policy", async () => {
  await assert.rejects(
    checkManagedFiles(
      fixture({
        files: managedFiles,
        author: releaseIdentity.author,
      }),
    ),
    /Release Please/,
  );

  await assert.rejects(
    checkManagedFiles(
      fixture({
        files: managedFiles,
        ...releaseIdentity,
        headRepository: 99,
      }),
    ),
    /Release Please/,
  );
});

test("a manual head commit on a release PR fails", async () => {
  await assert.rejects(
    checkManagedFiles(
      fixture({
        files: managedFiles,
        ...releaseIdentity,
        commitAuthor: "contributor",
      }),
    ),
    /head commit/,
  );
});

test("a custom token account is supported", async () => {
  await checkManagedFiles(
    fixture({
      files: managedFiles,
      branch: releaseIdentity.branch,
      author: "release-bot",
      releaseActor: "release-bot",
    }),
  );
});

test("renaming a managed file is still protected", async () => {
  await assert.rejects(
    checkManagedFiles(
      fixture({
        files: [{ filename: "other.txt", previous_filename: "version.txt" }],
      }),
    ),
    /Release Please/,
  );
});

test("an incomplete file listing fails closed", async () => {
  const options = fixture();
  options.github.paginate = async () => [];
  await assert.rejects(checkManagedFiles(options), /every changed file/);
});

test("a stale PR event cannot approve a newer head", async () => {
  const options = fixture();
  options.context.payload.pull_request.head.sha = "older-head";
  await assert.rejects(checkManagedFiles(options), /PR changed/);
});
