const { withMod } = require("expo/config-plugins");

function colorComponents(value) {
  if (!/^#[0-9a-f]{6}$/i.test(value)) {
    throw new Error(
      `Blank launch screen requires a six-digit hex color, received ${value}`,
    );
  }

  return [1, 3, 5].map((start) =>
    (Number.parseInt(value.slice(start, start + 2), 16) / 255).toFixed(8),
  );
}

module.exports = function withBlankLaunchScreen(
  config,
  { backgroundColor = "#ffffff" } = {},
) {
  return withMod(config, {
    platform: "ios",
    mod: "splashScreenStoryboard",
    action: async (modConfig) => {
      const document = modConfig.modResults.document;
      const view =
        document.scenes?.[0]?.scene?.[0]?.objects?.[0]?.viewController?.[0]
          ?.view?.[0];

      if (!view) {
        throw new Error("Could not find the iOS launch storyboard root view.");
      }

      const [red, green, blue] = colorComponents(backgroundColor);
      view.subviews = [{}];
      view.constraints = [{ constraint: [] }];
      view.color = [
        {
          $: {
            key: "backgroundColor",
            red,
            green,
            blue,
            alpha: "1",
            colorSpace: "custom",
            customColorSpace: "sRGB",
          },
        },
      ];

      document.resources ??= [{}];
      if (
        typeof document.resources[0] !== "object" ||
        document.resources[0] === null
      ) {
        document.resources[0] = {};
      }

      document.resources[0] = {
        namedColor: [
          {
            $: { name: "VestaLaunchBackground" },
            color: [
              {
                $: {
                  red,
                  green,
                  blue,
                  alpha: "1",
                  colorSpace: "custom",
                  customColorSpace: "sRGB",
                },
              },
            ],
          },
        ],
      };

      return modConfig;
    },
  });
};
