# Changelog

## [1.8.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.7.0...v1.8.0) (2026-01-31)


### Features

* restructure help intent ([e7a38ec](https://github.com/stkr22/private-assistant-switch-skill-py/commit/e7a38ec125d250b19618d3f7ba016329679bcda5))
* restructure help intent ([57ce345](https://github.com/stkr22/private-assistant-switch-skill-py/commit/57ce345fce1f23729c99e1f01d90c3bda26a970d))

## [1.7.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.6.3...v1.7.0) (2026-01-02)


### Features

* :sparkles: modernize skill infrastructure and remove aiosqlite [AI] ([6e43f78](https://github.com/stkr22/private-assistant-switch-skill-py/commit/6e43f789a3ff4c4530199442efadbd27a2a893fe))


### Bug Fixes

* :wrench: modernize database and MQTT configuration [AI] ([dcdfddb](https://github.com/stkr22/private-assistant-switch-skill-py/commit/dcdfddb9df4471ab72ce732fff9a3af25d2bf366))

## [1.6.3](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.6.2...v1.6.3) (2025-11-23)


### Bug Fixes

* update license to GPL-3.0-only in pyproject.toml ([91e2af6](https://github.com/stkr22/private-assistant-switch-skill-py/commit/91e2af65b9cfbf62c42868dcfbf17165e4d25f43))
* update Python version to 3.13.9 in Containerfile ([b1489c8](https://github.com/stkr22/private-assistant-switch-skill-py/commit/b1489c89a07228df35989b1c5e6a34113be916b1))

## [1.6.2](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.6.1...v1.6.2) (2025-10-24)


### Bug Fixes

* 🐛 correct entity key from plural to singular in device extraction [AI] ([88827f2](https://github.com/stkr22/private-assistant-switch-skill-py/commit/88827f2ee6f9f0ce56634c8ad632b45d42864a0a))

## [1.6.1](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.6.0...v1.6.1) (2025-10-23)


### Bug Fixes

* updating containerimage and capitalize AS ([da3d0eb](https://github.com/stkr22/private-assistant-switch-skill-py/commit/da3d0eb8851dec99251b586adf265923dd334bbe))

## [1.6.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.5.0...v1.6.0) (2025-10-21)


### Features

* :sparkles: migrate to private-assistant-commons 4.4.0+ closes [#67](https://github.com/stkr22/private-assistant-switch-skill-py/issues/67) [AI] ([7606bbb](https://github.com/stkr22/private-assistant-switch-skill-py/commit/7606bbbff3bbf2fd5c699623b66a3b5ff87ce632))


### Bug Fixes

* :bug: shorten module docstring to comply with line length limit [AI] ([70da023](https://github.com/stkr22/private-assistant-switch-skill-py/commit/70da02370a3dccc4fce3e42fd3d91037352dd7a3))
* exclude integration test as these are missing in github action ([db7bf4a](https://github.com/stkr22/private-assistant-switch-skill-py/commit/db7bf4a05f38e449036ae44b7ed3f3b3186513c8))

## [1.5.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.4.1...v1.5.0) (2025-07-26)


### Features

* :art: integrate Rich with Typer for consistent CLI styling [AI] ([cd2bf3d](https://github.com/stkr22/private-assistant-switch-skill-py/commit/cd2bf3de0f6ec6f3307a4f6372513cfb809e0e8f))
* integrate Rich with Typer for consistent CLI styling ([58a2f97](https://github.com/stkr22/private-assistant-switch-skill-py/commit/58a2f972b90116aafc96ffbb8afd677b79a05b5f))

## [1.4.1](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.4.0...v1.4.1) (2025-07-26)


### Bug Fixes

* :bug: resolve dependency injection in main.py [AI] ([3e53d24](https://github.com/stkr22/private-assistant-switch-skill-py/commit/3e53d2441573121db37fa28ebb25daa7f7e43f19))

## [1.4.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.3.0...v1.4.0) (2025-07-26)


### Features

* :safety_vest: strengthen type safety and validation [AI] ([fbc8020](https://github.com/stkr22/private-assistant-switch-skill-py/commit/fbc802005698c2e1159dea44309169a98208efb6))

## [1.3.0](https://github.com/stkr22/private-assistant-switch-skill-py/compare/v1.2.1...v1.3.0) (2025-07-26)


### Features

* :arrows_clockwise: add device cache refresh functionality [AI] ([8f6a39c](https://github.com/stkr22/private-assistant-switch-skill-py/commit/8f6a39c0cf319f2cd8fa51010f48545ef894fb78)), closes [#43](https://github.com/stkr22/private-assistant-switch-skill-py/issues/43)
* :sparkles: add typed exception hierarchy for better error handling [AI] ([5074848](https://github.com/stkr22/private-assistant-switch-skill-py/commit/5074848b4368c7d84f87002d933c632aec54b6bb)), closes [#42](https://github.com/stkr22/private-assistant-switch-skill-py/issues/42)
* add dedicated refresh.j2 template for device cache refresh ([b6d0fa4](https://github.com/stkr22/private-assistant-switch-skill-py/commit/b6d0fa4a0f3bd352edad5643af2da1a89aa000a9))


### Bug Fixes

* :lock: improve database session resource management [AI] ([641459f](https://github.com/stkr22/private-assistant-switch-skill-py/commit/641459f0233cbeff94e4530861da6aeffe420ad7)), closes [#44](https://github.com/stkr22/private-assistant-switch-skill-py/issues/44)
* :wrench: improve template loading with error handling [AI] ([a18380a](https://github.com/stkr22/private-assistant-switch-skill-py/commit/a18380aaef1e6d9a339ccadf61492ee11b9ef2d7)), closes [#42](https://github.com/stkr22/private-assistant-switch-skill-py/issues/42)
* improve core stability and performance ([9b0ae00](https://github.com/stkr22/private-assistant-switch-skill-py/commit/9b0ae008444a4c9fed881db9ae8ce66a520f00c4))
* linter issues ([16d0b12](https://github.com/stkr22/private-assistant-switch-skill-py/commit/16d0b129b7b8af12eb9320f8e984e16253ae3595))
* use BaseSkill add_task framework for concurrent MQTT operations ([137ab61](https://github.com/stkr22/private-assistant-switch-skill-py/commit/137ab61c413e758096169a5b05e9a4d33d1821ee))


### Performance Improvements

* :zap: implement concurrent MQTT operations for multiple devices [AI] ([6c27233](https://github.com/stkr22/private-assistant-switch-skill-py/commit/6c2723360da05ffe57e996d232d1098ac75d429e)), closes [#49](https://github.com/stkr22/private-assistant-switch-skill-py/issues/49)


### Documentation

* improve comprehensive documentation and code clarity ([df15eee](https://github.com/stkr22/private-assistant-switch-skill-py/commit/df15eeed3a484ccc872cd7ce4fa75afaeda23803))
* improve comprehensive documentation and code clarity [AI] ([d6819cb](https://github.com/stkr22/private-assistant-switch-skill-py/commit/d6819cb565791c8e24b36cfe8bfe5609daaaeeca))
