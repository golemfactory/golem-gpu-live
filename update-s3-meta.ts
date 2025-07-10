#!/usr/bin/env -S deno run --allow-net --allow-read --allow-env --allow-sys --env-file=.env

import { S3Client, ListObjectsV2Command, GetObjectCommand, PutObjectCommand } from "npm:@aws-sdk/client-s3";
import { fromEnv } from "npm:@aws-sdk/credential-providers";
import ProgressBar from "jsr:@deno-library/progress";

interface Version {
  id: string;
  path: string;
  sha256: string;
  created: string;
}

interface Channel {
  name: string;
  versions: Version[];
}

interface MetaData {
  channels: Channel[];
}

class S3MetaUpdater {
  private client: S3Client;
  private bucket: string;
  private region: string;

  constructor() {
    this.bucket = "repo-golem-gpu-live";
    this.region = "eu-central-1";
    this.client = new S3Client({
      region: this.region,
      credentials: fromEnv(),
    });
  }

  async downloadMetaJson(): Promise<MetaData> {
    try {
      const command = new GetObjectCommand({
        Bucket: this.bucket,
        Key: "images/meta.json",
      });

      const response = await this.client.send(command);
      const content = await response.Body?.transformToString();

      if (!content) {
        throw new Error("Empty response from S3");
      }

      return JSON.parse(content);
    } catch (error) {
      console.warn("Could not download existing meta.json, creating new one:", error);
      return { channels: [] };
    }
  }

  async uploadMetaJson(metaData: MetaData): Promise<void> {
    const command = new PutObjectCommand({
      Bucket: this.bucket,
      Key: "images/meta.json",
      Body: JSON.stringify(metaData, null, 2),
      ContentType: "application/json",
    });

    await this.client.send(command);
    console.log("✓ Successfully uploaded meta.json");
  }

  async listImages(): Promise<string[]> {
    const command = new ListObjectsV2Command({
      Bucket: this.bucket,
      Prefix: "images/",
    });

    const response = await this.client.send(command);
    const objects = response.Contents || [];

    return objects
      .filter(obj => obj.Key && obj.Key.endsWith('.img.xz') && obj.Key.startsWith('images/'))
      .map(obj => obj.Key!)
      .sort();
  }

  parseImagePath(path: string): { channel: string; version: string } | null {
    const filename = path.split('/').pop();
    if (!filename) return null;

    const match = filename.match(/^golem-gpu-live-([^-]+)-(.+)\.img\.xz$/);
    if (!match) return null;

    return {
      channel: match[1],
      version: match[2],
    };
  }

  async calculateSha256(path: string, progressCallback?: (downloaded: number, total: number, stage: string) => void): Promise<string> {
    try {
      const command = new GetObjectCommand({
        Bucket: this.bucket,
        Key: path,
      });

      const response = await this.client.send(command);
      const body = response.Body;

      if (!body) {
        throw new Error("Empty response body");
      }

      const contentLength = response.ContentLength || 0;
      const reader = body.transformToWebStream().getReader();

      let downloadedBytes = 0;
      let allChunks: Uint8Array[] = [];

      // Download with progress
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        allChunks.push(value);
        downloadedBytes += value.length;

        if (progressCallback) {
          progressCallback(downloadedBytes, contentLength, "downloading");
        }
      }

      // Combine all chunks
      const totalSize = allChunks.reduce((sum, chunk) => sum + chunk.length, 0);
      const allBytes = new Uint8Array(totalSize);
      let offset = 0;
      for (const chunk of allChunks) {
        allBytes.set(chunk, offset);
        offset += chunk.length;
      }

      // Calculate hash with progress
      if (progressCallback) {
        progressCallback(totalSize, totalSize, "hashing");
      }

      const hashBuffer = await crypto.subtle.digest('SHA-256', allBytes);
      const hashArray = Array.from(new Uint8Array(hashBuffer));
      return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
    } catch (error) {
      console.warn(`Could not calculate SHA256 for ${path}:`, error);
      return "";
    }
  }

  async updateMeta(): Promise<void> {
    console.log("🔄 Updating S3 meta.json...");

    const [metaData, imagePaths] = await Promise.all([
      this.downloadMetaJson(),
      this.listImages(),
    ]);

    console.log(`📁 Found ${imagePaths.length} images in S3`);

    const newChannels = new Map<string, Channel>();

    // Initialize channels from existing meta
    for (const channel of metaData.channels) {
      newChannels.set(channel.name, { ...channel });
    }

    // Count images that need processing
    const imagesToProcess = imagePaths.filter(imagePath => {
      const parsed = this.parseImagePath(imagePath);
      if (!parsed) return false;

      const { channel, version } = parsed;
      const existingChannel = metaData.channels.find(c => c.name === channel);
      const existingVersion = existingChannel?.versions.find(v => v.id === version);

      return !existingVersion;
    });

    if (imagesToProcess.length === 0) {
      console.log("✅ All images already indexed in meta.json");
      return;
    }

    console.log(`🔄 Processing ${imagesToProcess.length} new images...`);

    const progressBar = new ProgressBar({
      title: "Processing images",
      total: imagesToProcess.length,
      complete: "█",
      incomplete: "░",
      display: ":title :percent :bar :completed/:total :time :text"
    });

    // Process each image
    let processedCount = 0;
    for (const imagePath of imagePaths) {
      const parsed = this.parseImagePath(imagePath);
      if (!parsed) {
        console.log(`⚠️  Could not parse image path: ${imagePath}`);
        continue;
      }

      const { channel, version } = parsed;

      if (!newChannels.has(channel)) {
        newChannels.set(channel, { name: channel, versions: [] });
      }

      const channelData = newChannels.get(channel)!;
      const existingVersion = channelData.versions.find(v => v.id === version);

      if (!existingVersion) {
        // Show starting state without incrementing counter
        progressBar.render(processedCount, {
          text: `${channel}/${version} - starting...`
        });

        const sha256 = await this.calculateSha256(imagePath, (downloaded, total, stage) => {
          const percent = total > 0 ? (downloaded / total * 100).toFixed(1) : '0.0';
          const sizeStr = total > 0 ? `${(downloaded / 1024 / 1024).toFixed(1)}/${(total / 1024 / 1024).toFixed(1)}MB` : `${(downloaded / 1024 / 1024).toFixed(1)}MB`;
          progressBar.render(processedCount, {
            text: `${channel}/${version} - ${stage} ${percent}% (${sizeStr})`
          });
        });

        // Only increment counter after work is complete
        processedCount++;
        progressBar.render(processedCount, {
          text: `${channel}/${version} - completed`
        });

        const newVersion: Version = {
          id: version,
          path: imagePath.split('/').pop()!,
          sha256,
          created: new Date().toISOString(),
        };

        channelData.versions.push(newVersion);
        channelData.versions.sort((a, b) => b.created.localeCompare(a.created));
      }
    }

    progressBar.end();

    // Update meta data
    const updatedMeta: MetaData = {
      channels: Array.from(newChannels.values())
        .filter(channel => channel.versions.length > 0)
        .sort((a, b) => a.name.localeCompare(b.name)),
    };

    await this.uploadMetaJson(updatedMeta);

    console.log("✅ Meta.json update complete!");
    console.log(`📊 Channels: ${updatedMeta.channels.length}`);
    for (const channel of updatedMeta.channels) {
      console.log(`   ${channel.name}: ${channel.versions.length} versions`);
    }
  }
}

async function main() {
  const requiredEnvVars = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'];

  for (const envVar of requiredEnvVars) {
    if (!Deno.env.get(envVar)) {
      console.error(`❌ Missing required environment variable: ${envVar}`);
      Deno.exit(1);
    }
  }

  try {
    const updater = new S3MetaUpdater();
    await updater.updateMeta();
  } catch (error) {
    console.error("❌ Error updating meta.json:", error);
    Deno.exit(1);
  }
}

if (import.meta.main) {
  await main();
}
