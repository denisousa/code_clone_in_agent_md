# Pull Request
URL: https://github.com/apache/struts/pull/1667
Number: 1667
Title: Library updates for cve's, suppression cleanup and not fail github action job SonarCloud if SONARCLOUD_TOKEN not found (summary report instead).
State: open
Author: duttonw
Created at: 2026-04-21T01:40:29Z
Updated at: 2026-05-02T13:55:49Z
Merged at: None
Source branch: main
Target branch: main

## PR Description
[Library updates:](https://github.com/apache/struts/commit/4322579a011b128225dc092d660b562ddf328112) 

* profile jakartaee11: jakarta-ee from 11.0.0-M5 to 11.0.0
* Spring Version from 6.2.12 to 7.0.7 **(we are 2 months off OSS EOL for 6.2.x)**
* struts2-jasperreports-plugin: jasperreports from 6.21.3 to 6.21.5
* struts2-jasperreports7-plugin: jasperreports from 7.0.4 to 7.0.6
* profile jakartaee11: jakarta-ee from 11.0.0-M5 to 11.0.0

Dependancy suppression cleanup

[Sonar github workflow to be skipped if secret is not found](https://github.com/apache/struts/commit/1094328ec3de2eeb35de269a92d36aef48e28f19)

---

## Struts & Spring Compatibility Matrix

| Struts Plugin Version | Compatible Spring Version  | Spring OSS End of Life (EOL) |
|:----------------------|:---------------------------|:-----------------------------|
| **7.1.1**             | 6.2.x                      | 2026-06                      |
| **7.1.1**             | 7.0.7 (Jakarta EE 11 only) | 2027-06                      |

## General Conversation Comments
No general conversation comments found.

## Reviews
---
Author: lukaszlenart
State: CHANGES_REQUESTED
Submitted at: 2026-05-02T13:55:49Z
I would wait with switching to Spring 7.x and Jakarta 11 - this is a major upgrade and it must be properly communicated, we a JIRA ticket for that.

## Code Review Comments
---
Author: lukaszlenart
File: pom.xml
Line: 128
Created at: 2026-05-02T13:52:57Z
Diff snippet:
@@ -125,7 +125,7 @@
         <mockito.version>5.23.0</mockito.version>
         <ognl.version>3.4.11</ognl.version>
         <slf4j.version>2.0.17</slf4j.version>
-        <spring.version>6.2.12</spring.version>
+        <spring.version>7.0.7</spring.version>
Comment:
This is a major change, I would leave to the users
---
Author: lukaszlenart
File: pom.xml
Line: 161
Created at: 2026-05-02T13:53:28Z
Diff snippet:
@@ -157,8 +157,7 @@
         <profile>
             <id>jakartaee11</id>
             <properties>
-                <jakarta-ee.version>11.0.0-M5</jakarta-ee.version>
-                <spring.version>7.0.5</spring.version>
Comment:
I would keep Spring 7.x in a dedicated profile

## Commits
---
SHA: 4322579a011b128225dc092d660b562ddf328112
Author: william dutton
Message: Library updates:

* profile jakartaee11: jakarta-ee from 11.0.0-M5 to 11.0.0
* Spring Version from 6.2.12 to 7.0.7
* struts2-jasperreports-plugin: jasperreports from 6.21.3 to 6.21.5
* struts2-jasperreports7-plugin: jasperreports from 7.0.4 to 7.0.6
* profile jakartaee11: jakarta-ee from 11.0.0-M5 to 11.0.0

Dependancy suppression cleanup
---
SHA: 1094328ec3de2eeb35de269a92d36aef48e28f19
Author: william dutton
Message: Sonar github workflow to be skipped if secret is not found

## Changed Files
---
File: .github/workflows/maven.yml
Status: modified
Additions: 1
Deletions: 1
Changes: 2
---
File: .github/workflows/sonar.yml
Status: modified
Additions: 9
Deletions: 1
Changes: 10
---
File: plugins/jasperreports/pom.xml
Status: modified
Additions: 1
Deletions: 1
Changes: 2
---
File: plugins/jasperreports7/pom.xml
Status: modified
Additions: 1
Deletions: 1
Changes: 2
---
File: plugins/spring/README.md
Status: modified
Additions: 8
Deletions: 0
Changes: 8
---
File: pom.xml
Status: modified
Additions: 2
Deletions: 3
Changes: 5
---
File: src/etc/project-suppression.xml
Status: modified
Additions: 32
Deletions: 157
Changes: 189