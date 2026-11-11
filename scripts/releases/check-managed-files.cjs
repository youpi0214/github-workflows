/** Reject ordinary PR changes to files maintained by Release Please. */
const MANAGED_FILES = new Set([".release-please-manifest.json", "version.txt"]);

function sameAccount(login, expected) {
  return (
    typeof login === "string" && login.toLowerCase() === expected.toLowerCase()
  );
}

module.exports = async function checkManagedFiles({
  github,
  context,
  core,
  releaseActor,
}) {
  const repository = context.payload.repository;
  const eventPullRequest = context.payload.pull_request;

  const request = { ...context.repo, pull_number: eventPullRequest.number };
  const { data: pullRequest } = await github.rest.pulls.get(request);

  if (
    pullRequest.head.sha !== eventPullRequest.head.sha ||
    pullRequest.base.ref !== eventPullRequest.base.ref
  ) {
    throw new Error(
      "The PR changed while this check was starting. Run the check again.",
    );
  }

  if (pullRequest.base.ref !== repository.default_branch) {
    core.info("This PR does not target the default branch.");
    return;
  }

  const files = await github.paginate(github.rest.pulls.listFiles, {
    ...request,
    per_page: 100,
  });

  // The API caps file listings. Incomplete listings must not silently pass.
  if (files.length !== pullRequest.changed_files) {
    throw new Error(
      "Could not inspect every changed file. Maintainer review is required.",
    );
  }

  const managedChanges = files.filter(
    (file) =>
      MANAGED_FILES.has(file.filename) ||
      MANAGED_FILES.has(file.previous_filename),
  );

  if (managedChanges.length === 0) {
    core.info("No Release Please-managed files changed.");
    return;
  }

  const expectedBranch = `release-please--branches--${repository.default_branch}`;
  const trustedReleasePullRequest =
    sameAccount(pullRequest.user.login, releaseActor) &&
    pullRequest.head.repo?.id === repository.id &&
    pullRequest.head.ref === expectedBranch;

  if (!trustedReleasePullRequest) {
    throw new Error(
      "The release manifest and version.txt must be updated by Release Please. " +
        "Remove these changes from this PR and let the release workflow update them.",
    );
  }

  // Also catch a human adding a normal commit to the bot's release PR.
  const { data: commit } = await github.rest.repos.getCommit({
    ...context.repo,
    ref: pullRequest.head.sha,
  });

  if (!sameAccount(commit.author?.login, releaseActor)) {
    throw new Error(
      "The release PR head commit is not attributed to the configured release account.",
    );
  }

  core.info(
    "Managed file changes belong to the configured Release Please account and branch.",
  );
};
